from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from idea_check_backend.observability.runtime_events import (
    RuntimeEventLogger,
    RuntimeEventName,
)
from idea_check_backend.persistence.models import (
    QuestionStatus,
    RunStatus,
    SceneStatus,
    SessionStatus,
)
from idea_check_backend.persistence.repository import (
    AnswerRecord,
    QuestionInstanceRecord,
    ScenarioRunRecord,
    SceneInstanceRecord,
    SessionParticipantRecord,
    SqlAlchemyScenarioRuntimeRepository,
)
from idea_check_backend.scenario_engine.blueprint_loader import ScenarioBlueprintRepository
from idea_check_backend.shared_types.scenario_blueprint import ScenarioBlueprint, SceneDefinition


class RuntimeFlowError(Exception):
    pass


class RuntimeNotReadyError(RuntimeFlowError):
    pass


class InvalidAnswerSubmissionError(RuntimeFlowError):
    pass


@dataclass(slots=True, frozen=True)
class RuntimeQuestionView:
    id: str
    participant_id: str
    participant_slot: int
    question_key: str
    prompt_text: str | None
    status: str
    answered: bool
    answer_text: str | None


@dataclass(slots=True, frozen=True)
class RuntimeSceneState:
    scene_instance: SceneInstanceRecord
    questions: list[RuntimeQuestionView]
    phase: str
    revealed_answers: list[AnswerRecord]


@dataclass(slots=True, frozen=True)
class RuntimeState:
    run: ScenarioRunRecord
    active_scene: RuntimeSceneState | None


@dataclass(slots=True, frozen=True)
class SubmitAnswerResult:
    state: RuntimeState
    revealed_scene: RuntimeSceneState | None
    reveal_triggered: bool
    run_completed: bool
    advanced_to_next_scene: bool


class PairScenarioRuntimeService:
    def __init__(
        self,
        repository: SqlAlchemyScenarioRuntimeRepository,
        blueprint_repository: ScenarioBlueprintRepository | None = None,
        event_logger: RuntimeEventLogger | None = None,
    ) -> None:
        self._repository = repository
        self._blueprints = blueprint_repository or ScenarioBlueprintRepository()
        self._event_logger = event_logger or RuntimeEventLogger()

    async def start_run(self, session_id: str) -> RuntimeState:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise LookupError(f"Session not found: {session_id}")

        try:
            blueprint = self._blueprints.get(session.scenario_key)
            participants = await self._load_pair_participants(session_id, blueprint)
            now = datetime.now(UTC)
            first_scene = blueprint.scene_flow[0]
            run_runtime_state = self._build_run_runtime_state(
                blueprint=blueprint,
                scene=first_scene,
                scene_position=1,
                phase="collecting_answers",
            )

            run = await self._repository.create_scenario_run(
                session_id=session.id,
                scenario_key=session.scenario_key,
                scenario_version=blueprint.schema_version,
                status=RunStatus.WAITING_FOR_ANSWERS,
                runtime_state=run_runtime_state,
                current_scene_key=first_scene.scene_id,
                started_at=now,
            )
            self._event_logger.emit(
                RuntimeEventName.SCENARIO_RUN_STARTED,
                session_id=session.id,
                scenario_run_id=run.id,
                metadata={
                    "scenario_key": run.scenario_key,
                    "scenario_version": run.scenario_version,
                    "participant_count": len(participants),
                    "scene_position": 1,
                    "total_scenes": len(blueprint.scene_flow),
                    "state_after": run.runtime_state,
                },
            )

            scene = await self._repository.create_scene_instance(
                scenario_run_id=run.id,
                scene_key=first_scene.scene_id,
                position=1,
                status=SceneStatus.ACTIVE,
                state_payload=self._build_scene_state_payload(
                    first_scene,
                    phase="collecting_answers",
                ),
                generated_content={
                    "title": first_scene.title,
                    "purpose": first_scene.purpose,
                    "question_templates": list(first_scene.question_templates[:2]),
                },
                activated_at=now,
            )
            self._emit_scene_activated(run, scene, previous_state=None)

            await self._repository.update_session(
                session.id,
                status=SessionStatus.ACTIVE,
                lifecycle_state={
                    "run_id": run.id,
                    "current_scene_key": first_scene.scene_id,
                    "phase": "collecting_answers",
                },
                started_at=session.started_at or now,
            )

            for position, participant in enumerate(participants, start=1):
                prompt_text = self._select_prompt(first_scene, participant.slot)
                question = await self._repository.create_question_instance(
                    scene_instance_id=scene.id,
                    participant_id=participant.id,
                    question_key=f"{first_scene.scene_id}_slot_{participant.slot}",
                    position=position,
                    status=QuestionStatus.DELIVERED,
                    state_payload={"reveal_available": False, "participant_slot": participant.slot},
                    prompt_text=prompt_text,
                    prompt_payload={
                        "scene_key": first_scene.scene_id,
                        "participant_slot": participant.slot,
                        "question_template_index": min(
                            participant.slot - 1,
                            len(first_scene.question_templates) - 1,
                        ),
                    },
                    delivered_at=now,
                )
                self._event_logger.emit(
                    RuntimeEventName.QUESTION_DELIVERED,
                    session_id=run.session_id,
                    scenario_run_id=run.id,
                    scene_id=scene.id,
                    participant_id=participant.id,
                    participant_slot=participant.slot,
                    metadata={
                        "question_id": question.id,
                        "question_key": question.question_key,
                        "scene_key": scene.scene_key,
                        "delivery_status": question.status,
                    },
                )

            return await self.get_current_state(run.id)
        except Exception as error:
            self._event_logger.emit_error(
                error=error,
                session_id=session.id,
                metadata={"operation": "start_run", "scenario_key": session.scenario_key},
            )
            raise

    async def get_current_state(self, run_id: str) -> RuntimeState:
        run = await self._repository.get_scenario_run(run_id)
        if run is None:
            raise LookupError(f"ScenarioRun not found: {run_id}")

        active_scene = await self._repository.get_active_scene_for_run(run_id)
        if active_scene is None:
            return RuntimeState(run=run, active_scene=None)

        return RuntimeState(
            run=run,
            active_scene=await self._build_scene_state(run, active_scene),
        )

    async def submit_answer(
        self,
        *,
        run_id: str,
        participant_id: str,
        content_text: str,
        content_payload: dict[str, Any] | None = None,
    ) -> SubmitAnswerResult:
        run = await self._require_run(run_id)
        active_scene = await self._repository.get_active_scene_for_run(run_id)

        try:
            if run.status == RunStatus.COMPLETED:
                raise InvalidAnswerSubmissionError("Run is already completed")
            if active_scene is None:
                raise InvalidAnswerSubmissionError("Run does not have an active scene")

            questions = await self._repository.list_question_instances_for_scene(active_scene.id)
            question = next(
                (item for item in questions if item.participant_id == participant_id),
                None,
            )
            if question is None:
                raise InvalidAnswerSubmissionError(
                    "Participant is not assigned to the active scene"
                )
            if question.status == QuestionStatus.ANSWERED:
                raise InvalidAnswerSubmissionError("Participant has already answered this scene")

            answered_at = datetime.now(UTC)
            await self._repository.save_answer(
                question_instance_id=question.id,
                participant_id=participant_id,
                content_text=content_text,
                content_payload=content_payload,
            )
            await self._repository.update_question_instance(
                question.id,
                status=QuestionStatus.ANSWERED,
                state_payload={**question.state_payload, "reveal_available": False},
                answered_at=answered_at,
            )

            refreshed_questions = await self._repository.list_question_instances_for_scene(
                active_scene.id
            )
            answered_count = sum(
                item.status == QuestionStatus.ANSWERED for item in refreshed_questions
            )
            self._event_logger.emit(
                RuntimeEventName.ANSWER_SUBMITTED,
                session_id=run.session_id,
                scenario_run_id=run.id,
                scene_id=active_scene.id,
                participant_id=participant_id,
                participant_slot=question.state_payload.get("participant_slot"),
                metadata={
                    "question_id": question.id,
                    "question_key": question.question_key,
                    "answers_submitted_count": answered_count,
                    "expected_answers_count": len(refreshed_questions),
                    "state_before": run.runtime_state,
                    "content_payload_present": content_payload is not None,
                },
            )

            all_answered = all(
                item.status == QuestionStatus.ANSWERED for item in refreshed_questions
            )
            if not all_answered:
                await self._sync_waiting_state(run, active_scene, refreshed_questions)
                state = await self.get_current_state(run_id)
                return SubmitAnswerResult(
                    state=state,
                    revealed_scene=None,
                    reveal_triggered=False,
                    run_completed=False,
                    advanced_to_next_scene=False,
                )

            return await self._reveal_and_progress(run, active_scene, refreshed_questions)
        except Exception as error:
            self._event_logger.emit_error(
                error=error,
                session_id=run.session_id,
                scenario_run_id=run.id,
                scene_id=active_scene.id if active_scene is not None else None,
                participant_id=participant_id,
                metadata={"operation": "submit_answer"},
            )
            raise

    async def _reveal_and_progress(
        self,
        run: ScenarioRunRecord,
        active_scene: SceneInstanceRecord,
        questions: list[QuestionInstanceRecord],
    ) -> SubmitAnswerResult:
        answers = await self._repository.list_scene_answers_for_reveal(active_scene.id)
        for question in questions:
            await self._repository.update_question_instance(
                question.id,
                state_payload={**question.state_payload, "reveal_available": True},
            )

        blueprint = self._blueprints.get(run.scenario_key)
        current_scene_definition, current_index = self._find_scene_definition(
            blueprint,
            active_scene.scene_key,
        )
        next_scene_id, branch_reason = self._determine_next_scene_id(
            current_scene_definition,
            answers,
        )
        now = datetime.now(UTC)
        reveal_latency_seconds = self._seconds_since(active_scene.activated_at, now)

        self._event_logger.emit(
            RuntimeEventName.ANSWERS_REVEALED,
            session_id=run.session_id,
            scenario_run_id=run.id,
            scene_id=active_scene.id,
            metadata={
                "answers_submitted_count": len(answers),
                "time_to_second_answer_seconds": reveal_latency_seconds,
                "revealed_answer_ids": [answer.id for answer in answers],
                "state_before": active_scene.state_payload,
            },
        )

        await self._repository.update_scene_instance(
            active_scene.id,
            status=SceneStatus.COMPLETED,
            state_payload={
                **active_scene.state_payload,
                "phase": "revealed",
                "revealed": True,
                "revealed_answer_ids": [answer.id for answer in answers],
            },
            completed_at=now,
        )
        completed_scene = await self._repository.get_scene_instance(active_scene.id)
        if completed_scene is None:
            raise LookupError(f"SceneInstance not found: {active_scene.id}")
        self._event_logger.emit(
            RuntimeEventName.SCENE_COMPLETED,
            session_id=run.session_id,
            scenario_run_id=run.id,
            scene_id=completed_scene.id,
            metadata={
                "scene_key": completed_scene.scene_key,
                "scene_position": completed_scene.position,
                "state_before": active_scene.state_payload,
                "state_after": completed_scene.state_payload,
                "time_to_second_answer_seconds": reveal_latency_seconds,
            },
        )
        revealed_scene = await self._build_scene_state(run, completed_scene)

        self._event_logger.emit(
            RuntimeEventName.BRANCH_SELECTED,
            session_id=run.session_id,
            scenario_run_id=run.id,
            scene_id=completed_scene.id,
            metadata={
                "scene_key": completed_scene.scene_key,
                "selected_next_scene_id": next_scene_id,
                "branch_reason": branch_reason,
                "run_state_before": run.runtime_state,
            },
        )

        if next_scene_id is None:
            completed_run = await self._repository.update_scenario_run(
                run.id,
                status=RunStatus.COMPLETED,
                runtime_state={
                    **run.runtime_state,
                    "current_scene_index": current_index,
                    "current_scene_key": current_scene_definition.scene_id,
                    "phase": "completed",
                    "awaiting_participant_ids": [],
                    "revealed": True,
                },
                completed_at=now,
            )
            await self._repository.update_session(
                run.session_id,
                status=SessionStatus.COMPLETED,
                lifecycle_state={
                    "run_id": run.id,
                    "current_scene_key": current_scene_definition.scene_id,
                    "phase": "completed",
                },
                completed_at=now,
            )
            self._event_logger.emit(
                RuntimeEventName.RUN_COMPLETED,
                session_id=run.session_id,
                scenario_run_id=completed_run.id,
                scene_id=completed_scene.id,
                metadata={
                    "final_scene_key": completed_scene.scene_key,
                    "final_scene_position": completed_scene.position,
                    "state_after": completed_run.runtime_state,
                },
            )
            state = await self.get_current_state(completed_run.id)
            return SubmitAnswerResult(
                state=state,
                revealed_scene=revealed_scene,
                reveal_triggered=True,
                run_completed=True,
                advanced_to_next_scene=False,
            )

        next_scene_definition, next_scene_index = self._find_scene_definition(
            blueprint,
            next_scene_id,
        )
        next_scene = await self._repository.create_scene_instance(
            scenario_run_id=run.id,
            scene_key=next_scene_definition.scene_id,
            position=next_scene_index + 1,
            status=SceneStatus.ACTIVE,
            state_payload=self._build_scene_state_payload(
                next_scene_definition,
                phase="collecting_answers",
            ),
            generated_content={
                "title": next_scene_definition.title,
                "purpose": next_scene_definition.purpose,
                "question_templates": list(next_scene_definition.question_templates[:2]),
            },
            activated_at=now,
        )
        self._emit_scene_activated(run, next_scene, previous_state=run.runtime_state)
        participants = await self._load_pair_participants(run.session_id, blueprint)
        for position, participant in enumerate(participants, start=1):
            question = await self._repository.create_question_instance(
                scene_instance_id=next_scene.id,
                participant_id=participant.id,
                question_key=f"{next_scene_definition.scene_id}_slot_{participant.slot}",
                position=position,
                status=QuestionStatus.DELIVERED,
                state_payload={"reveal_available": False, "participant_slot": participant.slot},
                prompt_text=self._select_prompt(next_scene_definition, participant.slot),
                prompt_payload={
                    "scene_key": next_scene_definition.scene_id,
                    "participant_slot": participant.slot,
                    "question_template_index": min(
                        participant.slot - 1,
                        len(next_scene_definition.question_templates) - 1,
                    ),
                },
                delivered_at=now,
            )
            self._event_logger.emit(
                RuntimeEventName.QUESTION_DELIVERED,
                session_id=run.session_id,
                scenario_run_id=run.id,
                scene_id=next_scene.id,
                participant_id=participant.id,
                participant_slot=participant.slot,
                metadata={
                    "question_id": question.id,
                    "question_key": question.question_key,
                    "scene_key": next_scene.scene_key,
                    "delivery_status": question.status,
                },
            )

        updated_run = await self._repository.update_scenario_run(
            run.id,
            status=RunStatus.WAITING_FOR_ANSWERS,
            current_scene_key=next_scene_definition.scene_id,
            runtime_state=self._build_run_runtime_state(
                blueprint=blueprint,
                scene=next_scene_definition,
                scene_position=next_scene_index + 1,
                phase="collecting_answers",
            ),
        )
        await self._repository.update_session(
            run.session_id,
            lifecycle_state={
                "run_id": run.id,
                "current_scene_key": next_scene_definition.scene_id,
                "phase": "collecting_answers",
            },
        )

        state = await self.get_current_state(updated_run.id)
        return SubmitAnswerResult(
            state=state,
            revealed_scene=revealed_scene,
            reveal_triggered=True,
            run_completed=False,
            advanced_to_next_scene=True,
        )

    async def _sync_waiting_state(
        self,
        run: ScenarioRunRecord,
        active_scene: SceneInstanceRecord,
        questions: list[QuestionInstanceRecord],
    ) -> None:
        awaiting_participant_ids = [
            question.participant_id
            for question in questions
            if question.status != QuestionStatus.ANSWERED
        ]
        previous_scene_state = dict(active_scene.state_payload)
        updated_scene = await self._repository.update_scene_instance(
            active_scene.id,
            state_payload={
                **active_scene.state_payload,
                "phase": "waiting_for_partner",
                "revealed": False,
                "awaiting_participant_ids": awaiting_participant_ids,
            },
        )
        updated_run = await self._repository.update_scenario_run(
            run.id,
            status=RunStatus.WAITING_FOR_ANSWERS,
            runtime_state={
                **run.runtime_state,
                "phase": "waiting_for_partner",
                "awaiting_participant_ids": awaiting_participant_ids,
                "revealed": False,
            },
        )
        await self._repository.update_session(
            run.session_id,
            lifecycle_state={
                "run_id": run.id,
                "current_scene_key": active_scene.scene_key,
                "phase": "waiting_for_partner",
            },
        )
        self._event_logger.emit(
            RuntimeEventName.WAITING_FOR_SECOND_ANSWER,
            session_id=run.session_id,
            scenario_run_id=run.id,
            scene_id=active_scene.id,
            metadata={
                "answers_submitted_count": len(questions) - len(awaiting_participant_ids),
                "expected_answers_count": len(questions),
                "awaiting_participant_ids": awaiting_participant_ids,
                "state_before": previous_scene_state,
                "state_after": updated_scene.state_payload,
                "run_state_before": run.runtime_state,
                "run_state_after": updated_run.runtime_state,
                "time_since_scene_activation_seconds": self._seconds_since(
                    active_scene.activated_at,
                    datetime.now(UTC),
                ),
            },
        )

    async def _build_scene_state(
        self,
        run: ScenarioRunRecord,
        active_scene: SceneInstanceRecord,
    ) -> RuntimeSceneState:
        questions = await self._repository.list_question_instances_for_scene(active_scene.id)
        participants = await self._repository.list_session_participants(run.session_id)
        participant_by_id = {participant.id: participant for participant in participants}
        answers = await self._repository.list_scene_answers_for_reveal(active_scene.id)
        answers_by_question_id = {answer.question_instance_id: answer for answer in answers}
        revealed = bool(active_scene.state_payload.get("revealed"))
        question_views = [
            RuntimeQuestionView(
                id=question.id,
                participant_id=question.participant_id,
                participant_slot=participant_by_id[question.participant_id].slot,
                question_key=question.question_key,
                prompt_text=question.prompt_text,
                status=question.status,
                answered=question.status == QuestionStatus.ANSWERED,
                answer_text=answers_by_question_id[question.id].content_text if revealed else None,
            )
            for question in questions
        ]
        phase = (
            active_scene.state_payload.get("phase")
            or run.runtime_state.get("phase")
            or "collecting_answers"
        )
        return RuntimeSceneState(
            scene_instance=active_scene,
            questions=question_views,
            phase=phase,
            revealed_answers=answers if revealed else [],
        )

    async def _require_run(self, run_id: str) -> ScenarioRunRecord:
        run = await self._repository.get_scenario_run(run_id)
        if run is None:
            raise LookupError(f"ScenarioRun not found: {run_id}")
        return run

    async def _load_pair_participants(
        self,
        session_id: str,
        blueprint: ScenarioBlueprint,
    ) -> list[SessionParticipantRecord]:
        participants = await self._repository.list_session_participants(session_id)
        expected_count = blueprint.session_model.players_count
        if len(participants) != expected_count:
            raise RuntimeNotReadyError(
                "Expected "
                f"{expected_count} participants for session {session_id}, "
                f"got {len(participants)}"
            )
        return participants

    def _build_run_runtime_state(
        self,
        *,
        blueprint: ScenarioBlueprint,
        scene: SceneDefinition,
        scene_position: int,
        phase: str,
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "current_scene_key": scene.scene_id,
            "current_scene_index": scene_position - 1,
            "scene_position": scene_position,
            "total_scenes": len(blueprint.scene_flow),
            "awaiting_participant_ids": [],
            "revealed": False,
        }

    def _build_scene_state_payload(
        self,
        scene: SceneDefinition,
        *,
        phase: str,
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "scene_type": scene.scene_type,
            "psychological_stage": scene.psychological_stage,
            "revealed": False,
            "awaiting_participant_ids": [],
        }

    def _select_prompt(self, scene: SceneDefinition, participant_slot: int) -> str | None:
        if not scene.question_templates:
            return None
        prompt_index = min(participant_slot - 1, len(scene.question_templates) - 1)
        return scene.question_templates[prompt_index]

    def _find_scene_definition(
        self,
        blueprint: ScenarioBlueprint,
        scene_id: str,
    ) -> tuple[SceneDefinition, int]:
        for index, scene in enumerate(blueprint.scene_flow):
            if scene.scene_id == scene_id:
                return scene, index
        raise LookupError(f"Scene '{scene_id}' not found in blueprint '{blueprint.scenario_id}'")

    def _determine_next_scene_id(
        self,
        scene: SceneDefinition,
        answers: list[AnswerRecord],
    ) -> tuple[str | None, str]:
        if scene.branch_outcomes.end_scenario:
            return None, "end_scenario"
        if scene.branch_outcomes.default_next_scene_id is not None:
            return scene.branch_outcomes.default_next_scene_id, "default_next_scene"

        normalized_answers = [answer.content_text.strip().casefold() for answer in answers]
        if len(set(normalized_answers)) == 1 and scene.branch_outcomes.if_match is not None:
            return scene.branch_outcomes.if_match, "answers_matched"
        if scene.branch_outcomes.if_difference is not None:
            return scene.branch_outcomes.if_difference, "answers_differed"
        return scene.branch_outcomes.if_match, "fallback_if_match"

    def _emit_scene_activated(
        self,
        run: ScenarioRunRecord,
        scene: SceneInstanceRecord,
        *,
        previous_state: dict[str, Any] | None,
    ) -> None:
        self._event_logger.emit(
            RuntimeEventName.SCENE_ACTIVATED,
            session_id=run.session_id,
            scenario_run_id=run.id,
            scene_id=scene.id,
            metadata={
                "scene_key": scene.scene_key,
                "scene_position": scene.position,
                "state_before": previous_state,
                "state_after": scene.state_payload,
            },
        )

    def _seconds_since(
        self,
        start: datetime | None,
        end: datetime,
    ) -> float | None:
        if start is None:
            return None
        normalized_start = self._normalize_datetime(start)
        normalized_end = self._normalize_datetime(end)
        return round((normalized_end - normalized_start).total_seconds(), 3)

    def _normalize_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
