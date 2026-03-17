from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from idea_check_backend.api.schemas.pair_flow import (
    CreateSessionResponse,
    JoinSessionResponse,
    PairFlowStateKind,
    PairFlowStateResponse,
    PlayerSummaryResponse,
    ParticipantIdentity,
    QuestionStateResponse,
    RunSummary,
    SceneStateResponse,
    SessionSummary,
    SubmitAnswerOutcome,
    SubmitAnswerResponse,
)
from idea_check_backend.observability.runtime_events import (
    RuntimeEventLogger,
    RuntimeEventName,
)
from idea_check_backend.persistence.models import ParticipantStatus, SessionStatus
from idea_check_backend.persistence.repository import (
    ScenarioRunRecord,
    SessionParticipantRecord,
    SessionRecord,
    SummaryRecord,
    SqlAlchemyScenarioRuntimeRepository,
)
from idea_check_backend.runtime_service import (
    PairScenarioRuntimeService,
    RuntimeQuestionView,
    RuntimeSceneState,
    RuntimeState,
    SubmitAnswerResult,
)
from idea_check_backend.scenario_engine.blueprint_loader import ScenarioBlueprintRepository


class PairFlowApiError(Exception):
    pass


class SessionFullError(PairFlowApiError):
    pass


class RunUnavailableError(PairFlowApiError):
    pass


@dataclass(slots=True, frozen=True)
class _ParticipantContext:
    session: SessionRecord
    participant: SessionParticipantRecord
    run: ScenarioRunRecord | None


class PairFlowApiService:
    def __init__(
        self,
        *,
        repository: SqlAlchemyScenarioRuntimeRepository,
        runtime_service: PairScenarioRuntimeService,
        blueprint_repository: ScenarioBlueprintRepository,
        event_logger: RuntimeEventLogger | None = None,
    ) -> None:
        self._repository = repository
        self._runtime_service = runtime_service
        self._blueprints = blueprint_repository
        self._event_logger = event_logger or RuntimeEventLogger()

    async def create_session(self, display_name: str | None = None) -> CreateSessionResponse:
        session = await self._repository.create_session(scenario_key="date_route")
        self._event_logger.emit(
            RuntimeEventName.SESSION_CREATED,
            session_id=session.id,
            metadata={
                "scenario_key": session.scenario_key,
                "session_status": session.status,
            },
        )
        participant = await self._repository.add_session_participant(
            session_id=session.id,
            slot=1,
            display_name=display_name,
            status=ParticipantStatus.ACTIVE,
            joined_at=datetime.now(UTC),
        )
        self._event_logger.emit(
            RuntimeEventName.PARTICIPANT_JOINED,
            session_id=session.id,
            participant_id=participant.id,
            participant_slot=participant.slot,
            metadata={
                "participant_count": 1,
                "display_name_present": display_name is not None,
                "participant_status": participant.status,
            },
        )
        state = await self.get_current_state(session.id, participant.id)
        identity = self._serialize_participant_identity(participant)
        return CreateSessionResponse(access=identity, state=state)

    async def join_session(
        self,
        session_id: str,
        display_name: str | None = None,
    ) -> JoinSessionResponse:
        session = await self._require_session(session_id)
        participants = await self._repository.list_session_participants(session_id)
        expected_count = self._expected_participant_count(session.scenario_key)
        if len(participants) >= expected_count:
            raise SessionFullError(f"Session already has {expected_count} participants")

        participant = await self._repository.add_session_participant(
            session_id=session_id,
            slot=len(participants) + 1,
            display_name=display_name,
            status=ParticipantStatus.ACTIVE,
            joined_at=datetime.now(UTC),
        )
        self._event_logger.emit(
            RuntimeEventName.PARTICIPANT_JOINED,
            session_id=session_id,
            participant_id=participant.id,
            participant_slot=participant.slot,
            metadata={
                "participant_count": len(participants) + 1,
                "display_name_present": display_name is not None,
                "participant_status": participant.status,
            },
        )
        run_id = session.lifecycle_state.get("run_id")
        if run_id is None:
            state = await self._runtime_service.start_run(session_id)
            run_id = state.run.id

        state = await self.get_current_state(session_id, participant.id, run_id=run_id)
        identity = self._serialize_participant_identity(participant)
        return JoinSessionResponse(access=identity, state=state)

    async def get_current_state(
        self,
        session_id: str,
        participant_id: str,
        *,
        run_id: str | None = None,
    ) -> PairFlowStateResponse:
        context = await self._require_participant_context(
            session_id=session_id,
            participant_id=participant_id,
            run_id=run_id,
        )
        if context.run is None:
            return self._serialize_state(
                session=context.session,
                participant=context.participant,
                runtime_state=None,
            )

        runtime_state = await self._runtime_service.get_current_state(context.run.id)
        return self._serialize_state(
            session=context.session,
            participant=context.participant,
            runtime_state=runtime_state,
        )

    async def submit_answer(
        self,
        *,
        session_id: str,
        participant_id: str,
        content_text: str,
        content_payload: dict[str, object] | None = None,
    ) -> SubmitAnswerResponse:
        context = await self._require_participant_context(
            session_id=session_id,
            participant_id=participant_id,
        )
        if context.run is None:
            raise RunUnavailableError("Scenario run has not started yet")

        result = await self._runtime_service.submit_answer(
            run_id=context.run.id,
            participant_id=participant_id,
            content_text=content_text,
            content_payload=content_payload,
        )
        state = self._serialize_state(
            session=await self._require_session(session_id),
            participant=await self._require_participant(session_id, participant_id),
            runtime_state=result.state,
        )
        return SubmitAnswerResponse(
            outcome=self._determine_submit_outcome(result),
            state=state,
            reveal=self._serialize_scene(result.revealed_scene),
            advanced_to_next_scene=result.advanced_to_next_scene,
            run_completed=result.run_completed,
        )

    async def _require_participant_context(
        self,
        *,
        session_id: str,
        participant_id: str,
        run_id: str | None = None,
    ) -> _ParticipantContext:
        session = await self._require_session(session_id)
        participant = await self._require_participant(session_id, participant_id)
        effective_run_id = run_id or session.lifecycle_state.get("run_id")
        run = None
        if effective_run_id is not None:
            run = await self._repository.get_scenario_run(effective_run_id)
            if run is None:
                raise LookupError(f"ScenarioRun not found: {effective_run_id}")
        return _ParticipantContext(session=session, participant=participant, run=run)

    async def _require_session(self, session_id: str) -> SessionRecord:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise LookupError(f"Session not found: {session_id}")
        return session

    async def _require_participant(
        self,
        session_id: str,
        participant_id: str,
    ) -> SessionParticipantRecord:
        participant = await self._repository.get_session_participant(participant_id)
        if participant is None or participant.session_id != session_id:
            raise LookupError(f"Participant not found in session: {participant_id}")
        return participant

    def _expected_participant_count(self, scenario_key: str) -> int:
        blueprint = self._blueprints.get(scenario_key)
        return blueprint.session_model.players_count

    def _determine_submit_outcome(self, result: SubmitAnswerResult) -> SubmitAnswerOutcome:
        if result.run_completed:
            return SubmitAnswerOutcome.COMPLETED
        if result.advanced_to_next_scene:
            return SubmitAnswerOutcome.PROGRESSED
        if result.reveal_triggered:
            return SubmitAnswerOutcome.REVEAL
        return SubmitAnswerOutcome.WAITING

    def _serialize_state(
        self,
        *,
        session: SessionRecord,
        participant: SessionParticipantRecord,
        runtime_state: RuntimeState | None,
    ) -> PairFlowStateResponse:
        scene = runtime_state.active_scene if runtime_state is not None else None
        participant_question = next(
            (question for question in scene.questions if question.participant_id == participant.id),
            None,
        ) if scene is not None else None
        run_summary = None
        final_summary = None
        updated_at = session.updated_at
        if runtime_state is not None:
            updated_at = runtime_state.run.updated_at
            run_summary = RunSummary(
                id=runtime_state.run.id,
                status=runtime_state.run.status,
                phase=str(runtime_state.run.runtime_state.get("phase", "collecting_answers")),
                scene_position=runtime_state.run.runtime_state.get("scene_position"),
                total_scenes=runtime_state.run.runtime_state.get("total_scenes"),
                current_scene_key=runtime_state.run.current_scene_key,
            )
            final_summary = self._serialize_player_summary(
                runtime_state.summaries,
                participant.id,
            )

        state_kind = self._determine_state_kind(session, runtime_state, participant_question)
        return PairFlowStateResponse(
            session=SessionSummary(
                id=session.id,
                scenario_key=session.scenario_key,
                status=session.status,
                has_started_run=runtime_state is not None,
                active=session.status == SessionStatus.ACTIVE,
            ),
            participant=self._serialize_participant_identity(participant),
            run=run_summary,
            state_kind=state_kind,
            waiting_for_partner=state_kind == PairFlowStateKind.WAITING,
            can_reveal=state_kind == PairFlowStateKind.REVEAL,
            completed=state_kind == PairFlowStateKind.COMPLETED,
            current_scene=self._serialize_scene(scene),
            final_summary=final_summary,
            answered_current_question=(
                participant_question.answered if participant_question else False
            ),
            updated_at=updated_at,
        )

    def _determine_state_kind(
        self,
        session: SessionRecord,
        runtime_state: RuntimeState | None,
        participant_question: RuntimeQuestionView | None,
    ) -> PairFlowStateKind:
        if session.status == SessionStatus.COMPLETED or (
            runtime_state is not None and runtime_state.run.completed_at is not None
        ):
            return PairFlowStateKind.COMPLETED
        if runtime_state is None or runtime_state.active_scene is None:
            return PairFlowStateKind.WAITING

        phase = runtime_state.active_scene.phase
        if phase == "revealed":
            return PairFlowStateKind.REVEAL
        if phase == "waiting_for_partner":
            if participant_question is not None and participant_question.answered:
                return PairFlowStateKind.WAITING
            return PairFlowStateKind.ANSWERING

        if participant_question is not None and participant_question.answered:
            return PairFlowStateKind.WAITING
        return PairFlowStateKind.ANSWERING

    def _serialize_participant_identity(
        self,
        participant: SessionParticipantRecord,
    ) -> ParticipantIdentity:
        return ParticipantIdentity(
            id=participant.id,
            slot=participant.slot,
            display_name=participant.display_name,
            status=participant.status,
        )

    def _serialize_scene(
        self,
        scene: RuntimeSceneState | None,
    ) -> SceneStateResponse | None:
        if scene is None:
            return None
        return SceneStateResponse(
            id=scene.scene_instance.id,
            key=scene.scene_instance.scene_key,
            title=scene.scene_instance.generated_content.get("title"),
            purpose=scene.scene_instance.generated_content.get("purpose"),
            intro_text=scene.scene_instance.generated_content.get("intro_text"),
            transition_text=scene.scene_instance.generated_content.get("transition_text"),
            used_fallback=bool(scene.scene_instance.generated_content.get("used_fallback")),
            position=scene.scene_instance.position,
            status=scene.scene_instance.status,
            phase=scene.phase,
            revealed=bool(scene.scene_instance.state_payload.get("revealed")),
            questions=[
                QuestionStateResponse(
                    id=question.id,
                    participant_id=question.participant_id,
                    participant_slot=question.participant_slot,
                    question_key=question.question_key,
                    prompt_text=question.prompt_text,
                    status=question.status,
                    answered=question.answered,
                    answer_text=question.answer_text,
                )
                for question in scene.questions
            ],
        )

    def _serialize_player_summary(
        self,
        summaries: list[SummaryRecord],
        participant_id: str,
    ) -> PlayerSummaryResponse | None:
        for summary in summaries:
            if summary.content_payload.get("recipient_participant_id") != participant_id:
                continue
            return PlayerSummaryResponse(
                id=summary.id,
                kind=summary.kind,
                text=summary.content_text,
                subject_participant_id=summary.content_payload.get("subject_participant_id"),
                recipient_participant_id=summary.content_payload.get("recipient_participant_id"),
                focus=list(summary.content_payload.get("summary_focus", [])),
                tone=summary.content_payload.get("summary_tone"),
                forbidden_styles=list(
                    summary.content_payload.get("forbidden_summary_styles", [])
                ),
                used_fallback=bool(summary.content_payload.get("used_fallback", False)),
                generated_at=summary.generated_at,
            )
        return None
