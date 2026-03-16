from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import joinedload

from idea_check_backend.persistence.models import (
    Answer,
    ParticipantStatus,
    QuestionInstance,
    QuestionStatus,
    RunStatus,
    ScenarioRun,
    SceneInstance,
    SceneStatus,
    Session,
    SessionParticipant,
    SessionStatus,
    Summary,
    SummaryKind,
)
from idea_check_backend.shared_types.scenario import ScenarioDraft

_UNSET = object()


def _copy_payload(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value or {})


@dataclass(slots=True, frozen=True)
class SessionRecord:
    id: str
    external_ref: str | None
    scenario_key: str
    status: str
    lifecycle_state: dict[str, Any]
    metadata_payload: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class SessionParticipantRecord:
    id: str
    session_id: str
    slot: int
    role: str
    display_name: str | None
    status: str
    state_payload: dict[str, Any]
    generated_profile: dict[str, Any]
    joined_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class ScenarioRunRecord:
    id: str
    session_id: str
    scenario_key: str
    scenario_version: str
    status: str
    runtime_state: dict[str, Any]
    generated_content: dict[str, Any]
    current_scene_key: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class SceneInstanceRecord:
    id: str
    scenario_run_id: str
    scene_key: str
    position: int
    status: str
    state_payload: dict[str, Any]
    generated_content: dict[str, Any]
    activated_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class QuestionInstanceRecord:
    id: str
    scene_instance_id: str
    participant_id: str
    question_key: str
    position: int
    status: str
    state_payload: dict[str, Any]
    prompt_text: str | None
    prompt_payload: dict[str, Any]
    delivered_at: datetime | None
    answered_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class AnswerRecord:
    id: str
    question_instance_id: str
    participant_id: str
    content_text: str
    content_payload: dict[str, Any]
    submitted_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class SummaryRecord:
    id: str
    scenario_run_id: str
    scene_instance_id: str | None
    kind: str
    content_text: str
    content_payload: dict[str, Any]
    generated_at: datetime
    created_at: datetime
    updated_at: datetime


class ScenarioDraftRepository(Protocol):
    """Lightweight contract used by the blueprint bootstrap flow."""

    def save(self, draft: ScenarioDraft) -> None: ...

    def get(self, scenario_id: str) -> ScenarioDraft | None: ...


class InMemoryScenarioDraftRepository:
    """In-memory storage for generated scenario drafts used in bootstrap tests."""

    def __init__(self) -> None:
        self._items: dict[str, ScenarioDraft] = {}

    def save(self, draft: ScenarioDraft) -> None:
        self._items[draft.id] = draft

    def get(self, scenario_id: str) -> ScenarioDraft | None:
        return self._items.get(scenario_id)


class SqlAlchemyScenarioRuntimeRepository:
    """Persistence-backed runtime repository over SQLAlchemy sessions.

    The repository exposes runtime-oriented CRUD/update methods and returns
    detached snapshot records instead of ORM instances so that application
    services do not depend on SQLAlchemy state management.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_session(
        self,
        *,
        scenario_key: str,
        external_ref: str | None = None,
        status: str = SessionStatus.PENDING,
        lifecycle_state: Mapping[str, Any] | None = None,
        metadata_payload: Mapping[str, Any] | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> SessionRecord:
        """Create a new scenario session."""
        entity = Session(
            scenario_key=scenario_key,
            external_ref=external_ref,
            status=status,
            lifecycle_state=_copy_payload(lifecycle_state),
            metadata_payload=_copy_payload(metadata_payload),
            started_at=started_at,
            completed_at=completed_at,
        )
        return await self._create_and_refresh(entity, _to_session_record)

    async def get_session(self, session_id: str) -> SessionRecord | None:
        """Fetch a session by id."""
        return await self._get_record(Session, session_id, _to_session_record)

    async def update_session(
        self,
        session_id: str,
        *,
        status: str | object = _UNSET,
        lifecycle_state: Mapping[str, Any] | object = _UNSET,
        metadata_payload: Mapping[str, Any] | object = _UNSET,
        started_at: datetime | None | object = _UNSET,
        completed_at: datetime | None | object = _UNSET,
    ) -> SessionRecord:
        """Update mutable session fields including status and lifecycle state."""
        async with self._session_factory() as db_session:
            entity = await self._require(Session, session_id, db_session)
            self._apply_updates(
                entity,
                status=status,
                lifecycle_state=(
                    _copy_payload(cast(Mapping[str, Any] | None, lifecycle_state))
                    if lifecycle_state is not _UNSET
                    else _UNSET
                ),
                metadata_payload=(
                    _copy_payload(cast(Mapping[str, Any] | None, metadata_payload))
                    if metadata_payload is not _UNSET
                    else _UNSET
                ),
                started_at=started_at,
                completed_at=completed_at,
            )
            await db_session.commit()
            await db_session.refresh(entity)
            return _to_session_record(entity)

    async def add_session_participant(
        self,
        *,
        session_id: str,
        slot: int,
        role: str = "participant",
        display_name: str | None = None,
        status: str = ParticipantStatus.INVITED,
        state_payload: Mapping[str, Any] | None = None,
        generated_profile: Mapping[str, Any] | None = None,
        joined_at: datetime | None = None,
    ) -> SessionParticipantRecord:
        """Attach a participant to an existing session."""
        entity = SessionParticipant(
            session_id=session_id,
            slot=slot,
            role=role,
            display_name=display_name,
            status=status,
            state_payload=_copy_payload(state_payload),
            generated_profile=_copy_payload(generated_profile),
            joined_at=joined_at,
        )
        return await self._create_and_refresh(entity, _to_session_participant_record)

    async def get_session_participant(
        self,
        participant_id: str,
    ) -> SessionParticipantRecord | None:
        """Fetch a session participant by id."""
        return await self._get_record(
            SessionParticipant,
            participant_id,
            _to_session_participant_record,
        )

    async def list_session_participants(self, session_id: str) -> list[SessionParticipantRecord]:
        """Return session participants ordered by pair slot."""
        statement = (
            select(SessionParticipant)
            .where(SessionParticipant.session_id == session_id)
            .order_by(SessionParticipant.slot.asc(), SessionParticipant.created_at.asc())
        )
        return await self._fetch_all(statement, _to_session_participant_record)

    async def update_session_participant(
        self,
        participant_id: str,
        *,
        status: str | object = _UNSET,
        display_name: str | None | object = _UNSET,
        state_payload: Mapping[str, Any] | object = _UNSET,
        generated_profile: Mapping[str, Any] | object = _UNSET,
        joined_at: datetime | None | object = _UNSET,
    ) -> SessionParticipantRecord:
        """Update participant profile/state fields."""
        async with self._session_factory() as db_session:
            entity = await self._require(SessionParticipant, participant_id, db_session)
            self._apply_updates(
                entity,
                status=status,
                display_name=display_name,
                state_payload=(
                    _copy_payload(cast(Mapping[str, Any] | None, state_payload))
                    if state_payload is not _UNSET
                    else _UNSET
                ),
                generated_profile=(
                    _copy_payload(cast(Mapping[str, Any] | None, generated_profile))
                    if generated_profile is not _UNSET
                    else _UNSET
                ),
                joined_at=joined_at,
            )
            await db_session.commit()
            await db_session.refresh(entity)
            return _to_session_participant_record(entity)

    async def create_scenario_run(
        self,
        *,
        session_id: str,
        scenario_key: str,
        scenario_version: str = "v1",
        status: str = RunStatus.PENDING,
        runtime_state: Mapping[str, Any] | None = None,
        generated_content: Mapping[str, Any] | None = None,
        current_scene_key: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> ScenarioRunRecord:
        """Create a runtime scenario run within a session."""
        entity = ScenarioRun(
            session_id=session_id,
            scenario_key=scenario_key,
            scenario_version=scenario_version,
            status=status,
            runtime_state=_copy_payload(runtime_state),
            generated_content=_copy_payload(generated_content),
            current_scene_key=current_scene_key,
            started_at=started_at,
            completed_at=completed_at,
        )
        return await self._create_and_refresh(entity, _to_scenario_run_record)

    async def get_scenario_run(self, run_id: str) -> ScenarioRunRecord | None:
        """Fetch a scenario run by id."""
        return await self._get_record(ScenarioRun, run_id, _to_scenario_run_record)

    async def update_scenario_run(
        self,
        run_id: str,
        *,
        status: str | object = _UNSET,
        runtime_state: Mapping[str, Any] | object = _UNSET,
        generated_content: Mapping[str, Any] | object = _UNSET,
        current_scene_key: str | None | object = _UNSET,
        started_at: datetime | None | object = _UNSET,
        completed_at: datetime | None | object = _UNSET,
    ) -> ScenarioRunRecord:
        """Update run status, runtime state and current scene pointer."""
        async with self._session_factory() as db_session:
            entity = await self._require(ScenarioRun, run_id, db_session)
            self._apply_updates(
                entity,
                status=status,
                runtime_state=(
                    _copy_payload(cast(Mapping[str, Any] | None, runtime_state))
                    if runtime_state is not _UNSET
                    else _UNSET
                ),
                generated_content=(
                    _copy_payload(cast(Mapping[str, Any] | None, generated_content))
                    if generated_content is not _UNSET
                    else _UNSET
                ),
                current_scene_key=current_scene_key,
                started_at=started_at,
                completed_at=completed_at,
            )
            await db_session.commit()
            await db_session.refresh(entity)
            return _to_scenario_run_record(entity)

    async def get_runtime_state(self, run_id: str) -> dict[str, Any]:
        """Read the runtime state blob for a scenario run."""
        record = await self.get_scenario_run(run_id)
        if record is None:
            raise LookupError(f"ScenarioRun not found: {run_id}")
        return dict(record.runtime_state)

    async def update_runtime_state(
        self,
        run_id: str,
        runtime_state: Mapping[str, Any],
    ) -> ScenarioRunRecord:
        """Replace the runtime state blob for a scenario run."""
        return await self.update_scenario_run(run_id, runtime_state=runtime_state)

    async def create_scene_instance(
        self,
        *,
        scenario_run_id: str,
        scene_key: str,
        position: int,
        status: str = SceneStatus.PENDING,
        state_payload: Mapping[str, Any] | None = None,
        generated_content: Mapping[str, Any] | None = None,
        activated_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> SceneInstanceRecord:
        """Create a runtime scene instance inside a scenario run."""
        entity = SceneInstance(
            scenario_run_id=scenario_run_id,
            scene_key=scene_key,
            position=position,
            status=status,
            state_payload=_copy_payload(state_payload),
            generated_content=_copy_payload(generated_content),
            activated_at=activated_at,
            completed_at=completed_at,
        )
        return await self._create_and_refresh(entity, _to_scene_instance_record)

    async def get_scene_instance(self, scene_instance_id: str) -> SceneInstanceRecord | None:
        """Fetch a scene instance by id."""
        return await self._get_record(SceneInstance, scene_instance_id, _to_scene_instance_record)

    async def update_scene_instance(
        self,
        scene_instance_id: str,
        *,
        status: str | object = _UNSET,
        state_payload: Mapping[str, Any] | object = _UNSET,
        generated_content: Mapping[str, Any] | object = _UNSET,
        activated_at: datetime | None | object = _UNSET,
        completed_at: datetime | None | object = _UNSET,
    ) -> SceneInstanceRecord:
        """Update scene status and its runtime/generated payloads."""
        async with self._session_factory() as db_session:
            entity = await self._require(SceneInstance, scene_instance_id, db_session)
            self._apply_updates(
                entity,
                status=status,
                state_payload=(
                    _copy_payload(cast(Mapping[str, Any] | None, state_payload))
                    if state_payload is not _UNSET
                    else _UNSET
                ),
                generated_content=(
                    _copy_payload(cast(Mapping[str, Any] | None, generated_content))
                    if generated_content is not _UNSET
                    else _UNSET
                ),
                activated_at=activated_at,
                completed_at=completed_at,
            )
            await db_session.commit()
            await db_session.refresh(entity)
            return _to_scene_instance_record(entity)

    async def activate_scene_instance(
        self,
        scene_instance_id: str,
        *,
        activated_at: datetime | None = None,
    ) -> SceneInstanceRecord:
        """Mark a scene active and sync the parent run current scene key."""
        async with self._session_factory() as db_session:
            entity = await self._require(
                SceneInstance,
                scene_instance_id,
                db_session,
                options=(joinedload(SceneInstance.scenario_run),),
            )
            entity.status = SceneStatus.ACTIVE
            entity.activated_at = activated_at or datetime.now(UTC)
            entity.scenario_run.current_scene_key = entity.scene_key
            await db_session.commit()
            await db_session.refresh(entity)
            return _to_scene_instance_record(entity)

    async def get_active_scene_for_run(self, run_id: str) -> SceneInstanceRecord | None:
        """Return the current active scene for a run, ordered by scene position."""
        statement = (
            select(SceneInstance)
            .where(
                SceneInstance.scenario_run_id == run_id,
                SceneInstance.status == SceneStatus.ACTIVE,
            )
            .order_by(SceneInstance.position.asc())
            .limit(1)
        )
        return await self._fetch_one(statement, _to_scene_instance_record)

    async def create_question_instance(
        self,
        *,
        scene_instance_id: str,
        participant_id: str,
        question_key: str,
        position: int,
        status: str = QuestionStatus.PENDING,
        state_payload: Mapping[str, Any] | None = None,
        prompt_text: str | None = None,
        prompt_payload: Mapping[str, Any] | None = None,
        delivered_at: datetime | None = None,
        answered_at: datetime | None = None,
    ) -> QuestionInstanceRecord:
        """Create a participant-facing question instance inside a scene."""
        entity = QuestionInstance(
            scene_instance_id=scene_instance_id,
            participant_id=participant_id,
            question_key=question_key,
            position=position,
            status=status,
            state_payload=_copy_payload(state_payload),
            prompt_text=prompt_text,
            prompt_payload=_copy_payload(prompt_payload),
            delivered_at=delivered_at,
            answered_at=answered_at,
        )
        return await self._create_and_refresh(entity, _to_question_instance_record)

    async def get_question_instance(
        self,
        question_instance_id: str,
    ) -> QuestionInstanceRecord | None:
        """Fetch a question instance by id."""
        return await self._get_record(
            QuestionInstance,
            question_instance_id,
            _to_question_instance_record,
        )

    async def update_question_instance(
        self,
        question_instance_id: str,
        *,
        status: str | object = _UNSET,
        state_payload: Mapping[str, Any] | object = _UNSET,
        prompt_text: str | None | object = _UNSET,
        prompt_payload: Mapping[str, Any] | object = _UNSET,
        delivered_at: datetime | None | object = _UNSET,
        answered_at: datetime | None | object = _UNSET,
    ) -> QuestionInstanceRecord:
        """Update question delivery/answer status and prompt metadata."""
        async with self._session_factory() as db_session:
            entity = await self._require(QuestionInstance, question_instance_id, db_session)
            self._apply_updates(
                entity,
                status=status,
                state_payload=(
                    _copy_payload(cast(Mapping[str, Any] | None, state_payload))
                    if state_payload is not _UNSET
                    else _UNSET
                ),
                prompt_text=prompt_text,
                prompt_payload=(
                    _copy_payload(cast(Mapping[str, Any] | None, prompt_payload))
                    if prompt_payload is not _UNSET
                    else _UNSET
                ),
                delivered_at=delivered_at,
                answered_at=answered_at,
            )
            await db_session.commit()
            await db_session.refresh(entity)
            return _to_question_instance_record(entity)

    async def list_question_instances_for_scene(
        self,
        scene_instance_id: str,
    ) -> list[QuestionInstanceRecord]:
        """Return question instances for a scene ordered by question position."""
        statement = (
            select(QuestionInstance)
            .where(QuestionInstance.scene_instance_id == scene_instance_id)
            .order_by(QuestionInstance.position.asc(), QuestionInstance.created_at.asc())
        )
        return await self._fetch_all(statement, _to_question_instance_record)

    async def save_answer(
        self,
        *,
        question_instance_id: str,
        participant_id: str,
        content_text: str,
        content_payload: Mapping[str, Any] | None = None,
        submitted_at: datetime | None = None,
    ) -> AnswerRecord:
        """Persist a participant answer for a delivered question."""
        entity = Answer(
            question_instance_id=question_instance_id,
            participant_id=participant_id,
            content_text=content_text,
            content_payload=_copy_payload(content_payload),
        )
        if submitted_at is not None:
            entity.submitted_at = submitted_at
        return await self._create_and_refresh(entity, _to_answer_record)

    async def get_answer(self, answer_id: str) -> AnswerRecord | None:
        """Fetch a stored answer by id."""
        return await self._get_record(Answer, answer_id, _to_answer_record)

    async def list_scene_answers_for_reveal(self, scene_instance_id: str) -> list[AnswerRecord]:
        """Return scene answers ordered by question position and submission time."""
        statement = (
            select(Answer)
            .join(Answer.question_instance)
            .where(QuestionInstance.scene_instance_id == scene_instance_id)
            .order_by(
                QuestionInstance.position.asc(),
                Answer.submitted_at.asc(),
                Answer.created_at.asc(),
            )
        )
        return await self._fetch_all(statement, _to_answer_record)

    async def save_summary(
        self,
        *,
        scenario_run_id: str,
        content_text: str,
        kind: str = SummaryKind.SCENE,
        scene_instance_id: str | None = None,
        content_payload: Mapping[str, Any] | None = None,
        generated_at: datetime | None = None,
    ) -> SummaryRecord:
        """Persist a scene-level or run-level summary."""
        entity = Summary(
            scenario_run_id=scenario_run_id,
            scene_instance_id=scene_instance_id,
            kind=kind,
            content_text=content_text,
            content_payload=_copy_payload(content_payload),
        )
        if generated_at is not None:
            entity.generated_at = generated_at
        return await self._create_and_refresh(entity, _to_summary_record)

    async def list_run_summaries(self, scenario_run_id: str) -> list[SummaryRecord]:
        """Return all summaries belonging to a scenario run."""
        statement = (
            select(Summary)
            .where(Summary.scenario_run_id == scenario_run_id)
            .order_by(Summary.generated_at.asc(), Summary.created_at.asc())
        )
        return await self._fetch_all(statement, _to_summary_record)

    async def _create_and_refresh[T](
        self,
        entity: Any,
        serializer: callable[[T], Any],
    ) -> Any:
        async with self._session_factory() as db_session:
            db_session.add(entity)
            await db_session.commit()
            await db_session.refresh(entity)
            return serializer(entity)

    async def _get_record[T](
        self,
        model: type[T],
        entity_id: str,
        serializer: callable[[T], Any],
    ) -> Any | None:
        async with self._session_factory() as db_session:
            entity = await db_session.get(model, entity_id)
            if entity is None:
                return None
            return serializer(entity)

    async def _fetch_one[T](
        self,
        statement: Select[tuple[T]],
        serializer: callable[[T], Any],
    ) -> Any | None:
        async with self._session_factory() as db_session:
            entity = await db_session.scalar(statement)
            if entity is None:
                return None
            return serializer(entity)

    async def _fetch_all[T](
        self,
        statement: Select[tuple[T]],
        serializer: callable[[T], Any],
    ) -> list[Any]:
        async with self._session_factory() as db_session:
            result = await db_session.scalars(statement)
            return [serializer(item) for item in result.all()]

    async def _require[T](
        self,
        model: type[T],
        entity_id: str,
        db_session: AsyncSession,
        *,
        options: tuple[Any, ...] = (),
    ) -> T:
        entity = await db_session.get(model, entity_id, options=list(options))
        if entity is None:
            raise LookupError(f"{model.__name__} not found: {entity_id}")
        return entity

    @staticmethod
    def _apply_updates(entity: Any, **updates: object) -> None:
        for field_name, value in updates.items():
            if value is not _UNSET:
                setattr(entity, field_name, value)


ScenarioRepository = InMemoryScenarioDraftRepository


def _to_session_record(entity: Session) -> SessionRecord:
    return SessionRecord(
        id=entity.id,
        external_ref=entity.external_ref,
        scenario_key=entity.scenario_key,
        status=entity.status,
        lifecycle_state=dict(entity.lifecycle_state),
        metadata_payload=dict(entity.metadata_payload),
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_session_participant_record(entity: SessionParticipant) -> SessionParticipantRecord:
    return SessionParticipantRecord(
        id=entity.id,
        session_id=entity.session_id,
        slot=entity.slot,
        role=entity.role,
        display_name=entity.display_name,
        status=entity.status,
        state_payload=dict(entity.state_payload),
        generated_profile=dict(entity.generated_profile),
        joined_at=entity.joined_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_scenario_run_record(entity: ScenarioRun) -> ScenarioRunRecord:
    return ScenarioRunRecord(
        id=entity.id,
        session_id=entity.session_id,
        scenario_key=entity.scenario_key,
        scenario_version=entity.scenario_version,
        status=entity.status,
        runtime_state=dict(entity.runtime_state),
        generated_content=dict(entity.generated_content),
        current_scene_key=entity.current_scene_key,
        started_at=entity.started_at,
        completed_at=entity.completed_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_scene_instance_record(entity: SceneInstance) -> SceneInstanceRecord:
    return SceneInstanceRecord(
        id=entity.id,
        scenario_run_id=entity.scenario_run_id,
        scene_key=entity.scene_key,
        position=entity.position,
        status=entity.status,
        state_payload=dict(entity.state_payload),
        generated_content=dict(entity.generated_content),
        activated_at=entity.activated_at,
        completed_at=entity.completed_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_question_instance_record(entity: QuestionInstance) -> QuestionInstanceRecord:
    return QuestionInstanceRecord(
        id=entity.id,
        scene_instance_id=entity.scene_instance_id,
        participant_id=entity.participant_id,
        question_key=entity.question_key,
        position=entity.position,
        status=entity.status,
        state_payload=dict(entity.state_payload),
        prompt_text=entity.prompt_text,
        prompt_payload=dict(entity.prompt_payload),
        delivered_at=entity.delivered_at,
        answered_at=entity.answered_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_answer_record(entity: Answer) -> AnswerRecord:
    return AnswerRecord(
        id=entity.id,
        question_instance_id=entity.question_instance_id,
        participant_id=entity.participant_id,
        content_text=entity.content_text,
        content_payload=dict(entity.content_payload),
        submitted_at=entity.submitted_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def _to_summary_record(entity: Summary) -> SummaryRecord:
    return SummaryRecord(
        id=entity.id,
        scenario_run_id=entity.scenario_run_id,
        scene_instance_id=entity.scene_instance_id,
        kind=entity.kind,
        content_text=entity.content_text,
        content_payload=dict(entity.content_payload),
        generated_at=entity.generated_at,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )
