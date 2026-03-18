from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from idea_check_backend.llm_service.client import LLMServiceClient, SceneGenerationResult
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
    SummaryRecord,
    SqlAlchemyScenarioRuntimeRepository,
)
from idea_check_backend.scenario_engine.blueprint_loader import ScenarioBlueprintRepository
from idea_check_backend.shared_types.scenario import SceneGenerationPayload
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
    summaries: list[SummaryRecord]


@dataclass(slots=True, frozen=True)
class SubmitAnswerResult:
    state: RuntimeState
    revealed_scene: RuntimeSceneState | None
    reveal_triggered: bool
    run_completed: bool
    advanced_to_next_scene: bool


@dataclass(slots=True, frozen=True)
class SummarySubjectContext:
    participant: SessionParticipantRecord
    answers: list[dict[str, Any]]
    topics: list[str]
    preference_observations: list[str]
    vibe_observations: list[str]


@dataclass(slots=True, frozen=True)
class SummaryGenerationContext:
    scenario_run_id: str
    completed_at: datetime
    summary_focus: list[str]
    summary_tone: str
    forbidden_summary_styles: list[str]
    participants: list[SessionParticipantRecord]
    subjects: dict[str, SummarySubjectContext]


SummaryGenerator = Callable[[SummaryGenerationContext, SessionParticipantRecord], dict[str, Any]]


class PairScenarioRuntimeService:
    def __init__(
        self,
        repository: SqlAlchemyScenarioRuntimeRepository,
        blueprint_repository: ScenarioBlueprintRepository | None = None,
        event_logger: RuntimeEventLogger | None = None,
        llm_client: LLMServiceClient | None = None,
        summary_generator: SummaryGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._blueprints = blueprint_repository or ScenarioBlueprintRepository()
        self._event_logger = event_logger or RuntimeEventLogger()
        self._llm_client = llm_client or LLMServiceClient()
        self._summary_generator = summary_generator or self._build_player_summary

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

            generated_scene = self._generate_scene_content(
                run=run,
                blueprint=blueprint,
                scene=first_scene,
                scene_position=1,
                previous_answers=[],
                branch_reason=None,
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
                generated_content=generated_scene,
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
                prompt_text = self._select_scene_prompt(generated_scene["questions"])
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
                        "question_source": "generated",
                        "question_index": self._resolve_scene_prompt_index(
                            generated_scene["questions"]
                        ),
                        "question_delivery_mode": "shared_scene_prompt",
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
        summaries = await self._repository.list_run_summaries(run_id)
        if active_scene is None:
            return RuntimeState(run=run, active_scene=None, summaries=summaries)

        return RuntimeState(
            run=run,
            active_scene=await self._build_scene_state(run, active_scene),
            summaries=summaries,
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
            summary_context = await self._build_summary_generation_context(
                run=run,
                blueprint=blueprint,
                completed_at=now,
            )
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
                generated_content={
                    **run.generated_content,
                    "summary_context": self._serialize_summary_context(summary_context),
                },
                completed_at=now,
            )
            await self._generate_and_store_run_summaries(
                run=completed_run,
                summary_context=summary_context,
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
        generated_scene = self._generate_scene_content(
            run=run,
            blueprint=blueprint,
            scene=next_scene_definition,
            scene_position=next_scene_index + 1,
            previous_answers=answers,
            branch_reason=branch_reason,
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
            generated_content=generated_scene,
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
                prompt_text=self._select_scene_prompt(generated_scene["questions"]),
                prompt_payload={
                    "scene_key": next_scene_definition.scene_id,
                    "participant_slot": participant.slot,
                    "question_source": "generated",
                    "question_index": self._resolve_scene_prompt_index(
                        generated_scene["questions"]
                    ),
                    "question_delivery_mode": "shared_scene_prompt",
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

    def _generate_scene_content(
        self,
        *,
        run: ScenarioRunRecord,
        blueprint: ScenarioBlueprint,
        scene: SceneDefinition,
        scene_position: int,
        previous_answers: list[AnswerRecord],
        branch_reason: str | None,
    ) -> dict[str, Any]:
        payload = self._build_scene_generation_payload(
            blueprint=blueprint,
            scene=scene,
            previous_answers=previous_answers,
            branch_reason=branch_reason,
        )
        self._event_logger.emit(
            RuntimeEventName.SCENE_GENERATION_REQUESTED,
            session_id=run.session_id,
            scenario_run_id=run.id,
            metadata={
                "scene_key": scene.scene_id,
                "scene_position": scene_position,
                "question_count_target": payload.question_count_target,
                "has_previous_answers": bool(previous_answers),
                "branch_reason": branch_reason,
            },
        )

        result: SceneGenerationResult | None = None
        validation_error: str | None = None
        try:
            result = self._llm_client.generate_scene(payload)
        except Exception as error:
            validation_error = str(error)

        if result is None:
            fallback = self._llm_client.build_fallback_generation(payload)
            generated_content = {
                "title": scene.title,
                "purpose": scene.purpose,
                "intro_text": fallback.intro_text,
                "questions": list(fallback.questions),
                "transition_text": fallback.transition_text,
                "used_fallback": True,
                "generation_payload": payload.model_dump(mode="json"),
                "generation_log": {
                    "scene_id": payload.scene_id,
                    "provider": self._llm_client.settings.llm_provider,
                    "model": self._llm_client.settings.llm_model,
                    "prompt": self._llm_client.build_prompt(payload),
                    "raw_response": "<runtime_generation_exception>",
                    "validation_error": validation_error,
                    "used_fallback": True,
                },
            }
        else:
            generated_content = {
                "title": scene.title,
                "purpose": scene.purpose,
                "intro_text": result.generation.intro_text,
                "questions": list(result.generation.questions),
                "transition_text": result.generation.transition_text,
                "used_fallback": result.generation.used_fallback,
                "generation_payload": payload.model_dump(mode="json"),
                "generation_log": result.log.model_dump(mode="json"),
            }

        self._event_logger.emit(
            RuntimeEventName.SCENE_GENERATION_COMPLETED,
            session_id=run.session_id,
            scenario_run_id=run.id,
            metadata={
                "scene_key": scene.scene_id,
                "scene_position": scene_position,
                "used_fallback": generated_content["used_fallback"],
                "provider": generated_content["generation_log"]["provider"],
                "model": generated_content["generation_log"]["model"],
                "validation_error": generated_content["generation_log"]["validation_error"],
            },
        )
        return generated_content

    def _build_scene_generation_payload(
        self,
        *,
        blueprint: ScenarioBlueprint,
        scene: SceneDefinition,
        previous_answers: list[AnswerRecord],
        branch_reason: str | None,
    ) -> SceneGenerationPayload:
        return SceneGenerationPayload(
            scene_id=scene.scene_id,
            scene_type=scene.scene_type,
            scene_title=scene.title,
            scene_purpose=scene.purpose,
            psychological_goal=scene.psychological_goal,
            ladder_stages=scene.ladder_stages,
            allowed_question_families=scene.allowed_question_families,
            forbidden_question_families=scene.forbidden_question_families,
            question_templates=scene.question_templates,
            question_count_target=scene.question_count_target,
            transition_goal=scene.transition_goal,
            selected_world=blueprint.world_setup.preset_world_ids[0],
            selected_tone=blueprint.world_setup.allowed_tones[0],
            product_goal=blueprint.product_goal,
            experience_principles=blueprint.experience_principles,
            max_answer_length_chars=blueprint.question_policy.max_answer_length_chars,
            previous_answers_summary=self._summarize_answers(previous_answers),
            branching_context=self._build_branching_context(branch_reason, previous_answers),
        )

    def _summarize_answers(self, answers: list[AnswerRecord]) -> str | None:
        if not answers:
            return None
        return " | ".join(
            f"participant_{index}: {answer.content_text.strip()}"
            for index, answer in enumerate(answers, start=1)
        )

    def _build_branching_context(
        self,
        branch_reason: str | None,
        answers: list[AnswerRecord],
    ) -> str | None:
        if branch_reason is None and not answers:
            return None
        if branch_reason is None:
            return f"Previous scene answers captured: {len(answers)}"
        return f"Branch reason: {branch_reason}. Previous scene answers captured: {len(answers)}"

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

    def _select_scene_prompt(self, prompts: list[str]) -> str | None:
        if not prompts:
            return None
        return prompts[self._resolve_scene_prompt_index(prompts)]

    def _resolve_scene_prompt_index(self, prompts: list[str]) -> int:
        # MVP rule: one scene maps to one shared prompt for both participants.
        # If generation returns multiple questions, runtime uses only the first one.
        return 0

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

    async def _build_summary_generation_context(
        self,
        *,
        run: ScenarioRunRecord,
        blueprint: ScenarioBlueprint,
        completed_at: datetime,
    ) -> SummaryGenerationContext:
        participants = await self._repository.list_session_participants(run.session_id)
        scenes = await self._repository.list_scene_instances_for_run(run.id)
        answers_by_participant: dict[str, list[dict[str, Any]]] = {
            participant.id: [] for participant in participants
        }

        for scene in scenes:
            questions = await self._repository.list_question_instances_for_scene(scene.id)
            question_by_id = {question.id: question for question in questions}
            scene_answers = await self._repository.list_scene_answers_for_reveal(scene.id)
            for answer in scene_answers:
                question = question_by_id.get(answer.question_instance_id)
                answers_by_participant.setdefault(answer.participant_id, []).append(
                    {
                        "scene_key": scene.scene_key,
                        "scene_position": scene.position,
                        "question_key": question.question_key if question is not None else None,
                        "prompt_text": question.prompt_text if question is not None else None,
                        "answer_text": answer.content_text.strip(),
                    }
                )

        subjects = {
            participant.id: self._build_subject_summary_context(
                participant=participant,
                answers=answers_by_participant.get(participant.id, []),
            )
            for participant in participants
        }
        policy = blueprint.summary_policy
        return SummaryGenerationContext(
            scenario_run_id=run.id,
            completed_at=completed_at,
            summary_focus=list(policy.summary_focus),
            summary_tone=policy.summary_tone,
            forbidden_summary_styles=list(policy.forbidden_summary_styles),
            participants=participants,
            subjects=subjects,
        )

    def _build_subject_summary_context(
        self,
        *,
        participant: SessionParticipantRecord,
        answers: list[dict[str, Any]],
    ) -> SummarySubjectContext:
        snippets = [item["answer_text"] for item in answers if item["answer_text"]]
        topics = self._extract_topics(answers)
        preference_observations = [
            f"chasto vozvrashchalsya k temam: {', '.join(snippets[:2])}"
            if len(snippets) >= 2
            else f"otmetil: {snippets[0]}"
            for _ in [0]
            if snippets
        ]
        vibe_observations = self._extract_vibe_observations(snippets)
        return SummarySubjectContext(
            participant=participant,
            answers=answers,
            topics=topics,
            preference_observations=preference_observations,
            vibe_observations=vibe_observations,
        )

    def _extract_topics(self, answers: list[dict[str, Any]]) -> list[str]:
        topics: list[str] = []
        for item in answers:
            prompt_text = (item.get("prompt_text") or "").strip()
            answer_text = (item.get("answer_text") or "").strip()
            if answer_text:
                topics.append(answer_text)
            elif prompt_text:
                topics.append(prompt_text)

        unique_topics: list[str] = []
        seen: set[str] = set()
        for topic in topics:
            normalized = topic.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_topics.append(self._trim_text(topic, limit=72))
            if len(unique_topics) == 3:
                break
        return unique_topics

    def _extract_vibe_observations(self, snippets: list[str]) -> list[str]:
        if not snippets:
            return ["otvechal bez yavnyh signalov, poetomu luchshe opiratsya na konkretiku iz vashego marshruta"]

        lowered = " ".join(snippets).casefold()
        observations: list[str] = []
        if any(token in lowered for token in ("cafe", "tea", "coffee", "quiet", "spok", "walk")):
            observations.append("tyanetsya k spokojnomu, ne-peregruzhennomu formatu")
        if any(token in lowered for token in ("play", "fun", "laugh", "adventure", "game")):
            observations.append("otzyvaetsya na legkost i igrovuyu dinamiku")
        if any(token in lowered for token in ("slow", "pause", "soft", "gentle")):
            observations.append("predpochitaet myagkiy temp razgovora")
        if not observations:
            observations.append("v otvetah chuvstvuetsya konkretnyy, prizemlennyy vibe bez pozerskih formulirovok")
        return observations[:2]

    async def _generate_and_store_run_summaries(
        self,
        *,
        run: ScenarioRunRecord,
        summary_context: SummaryGenerationContext,
    ) -> None:
        participants = summary_context.participants
        if len(participants) < 2:
            return

        for participant in participants:
            other_participant = next(
                candidate for candidate in participants if candidate.id != participant.id
            )
            try:
                generated = self._summary_generator(summary_context, participant)
                used_fallback = bool(generated.get("used_fallback", False))
            except Exception as error:
                self._event_logger.emit_error(
                    error=error,
                    session_id=run.session_id,
                    scenario_run_id=run.id,
                    participant_id=participant.id,
                    participant_slot=participant.slot,
                    metadata={"operation": "generate_summary"},
                )
                generated = self._build_fallback_player_summary(summary_context, participant)
                used_fallback = True

            payload = {
                **generated.get("content_payload", {}),
                "recipient_participant_id": participant.id,
                "subject_participant_id": other_participant.id,
                "summary_focus": summary_context.summary_focus,
                "summary_tone": summary_context.summary_tone,
                "forbidden_summary_styles": summary_context.forbidden_summary_styles,
                "used_fallback": used_fallback,
            }
            await self._repository.save_summary(
                scenario_run_id=run.id,
                kind="run",
                content_text=generated["content_text"],
                content_payload=payload,
                generated_at=summary_context.completed_at,
            )

    def _build_player_summary(
        self,
        summary_context: SummaryGenerationContext,
        recipient: SessionParticipantRecord,
    ) -> dict[str, Any]:
        subject = next(
            participant for participant in summary_context.participants if participant.id != recipient.id
        )
        subject_context = summary_context.subjects[subject.id]
        subject_name = subject.display_name or "Vash partner"
        portrait = (
            f"{subject_name} po marshrutu pokazalsya chelovekom, kotoromu blizki "
            f"{self._join_items(subject_context.preference_observations or subject_context.topics or ['zhivye, konkretnye situacii'])}."
        )
        vibe = (
            "Po vibe bylo zametno, chto on/ona "
            f"{self._join_items(subject_context.vibe_observations)}."
        )
        topics = (
            "V realnom razgovore mozhno prodolzhit: "
            f"{self._join_items(subject_context.topics or ['samyj komfortnyj format vstrechi', 'temp i atmosfera vechera'])}."
        )
        return {
            "content_text": " ".join((portrait, vibe, topics)),
            "used_fallback": False,
            "content_payload": {
                "sections": {
                    "portrait": portrait,
                    "vibe": vibe,
                    "topics": subject_context.topics,
                }
            },
        }

    def _build_fallback_player_summary(
        self,
        summary_context: SummaryGenerationContext,
        recipient: SessionParticipantRecord,
    ) -> dict[str, Any]:
        subject = next(
            participant for participant in summary_context.participants if participant.id != recipient.id
        )
        subject_context = summary_context.subjects[subject.id]
        subject_name = subject.display_name or "Vash partner"
        topics = subject_context.topics or [
            "chto emu/ey osobenno nravitsya v formate vstrechi",
            "kakoy temp razgovora samyy komfortnyy",
        ]
        text = (
            f"{subject_name} ostavil teploe vpechatlenie i daval konkretnye signaly o tom, "
            f"chto emu/ey blizko. Bez diagnozov i obobshcheniy: luchshe vsego prodolzhit "
            f"razgovor vokrug tem {self._join_items(topics)}."
        )
        return {
            "content_text": text,
            "used_fallback": True,
            "content_payload": {
                "sections": {
                    "portrait": text,
                    "vibe": None,
                    "topics": topics,
                }
            },
        }

    def _serialize_summary_context(
        self,
        summary_context: SummaryGenerationContext,
    ) -> dict[str, Any]:
        return {
            "scenario_run_id": summary_context.scenario_run_id,
            "completed_at": summary_context.completed_at.isoformat(),
            "summary_focus": list(summary_context.summary_focus),
            "summary_tone": summary_context.summary_tone,
            "forbidden_summary_styles": list(summary_context.forbidden_summary_styles),
            "participants": [
                {
                    "participant_id": participant.id,
                    "slot": participant.slot,
                    "display_name": participant.display_name,
                    "topics": summary_context.subjects[participant.id].topics,
                    "preference_observations": summary_context.subjects[
                        participant.id
                    ].preference_observations,
                    "vibe_observations": summary_context.subjects[
                        participant.id
                    ].vibe_observations,
                    "answers": summary_context.subjects[participant.id].answers,
                }
                for participant in summary_context.participants
            ],
        }

    def _trim_text(self, value: str, *, limit: int) -> str:
        trimmed = " ".join(value.split())
        if len(trimmed) <= limit:
            return trimmed
        return trimmed[: limit - 3].rstrip() + "..."

    def _join_items(self, items: list[str]) -> str:
        cleaned = [item.strip() for item in items if item and item.strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} i {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])} i {cleaned[-1]}"
