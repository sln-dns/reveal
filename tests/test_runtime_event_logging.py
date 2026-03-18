from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from idea_check_backend.api.pair_flow_service import PairFlowApiService
from idea_check_backend.llm_service.client import LLMServiceClient
from idea_check_backend.observability.runtime_events import RuntimeEventLogger, RuntimeEventName
from idea_check_backend.persistence.db import make_async_engine
from idea_check_backend.persistence.models import Base
from idea_check_backend.persistence.repository import SqlAlchemyScenarioRuntimeRepository
from idea_check_backend.runtime_service import PairScenarioRuntimeService
from idea_check_backend.scenario_engine.blueprint_loader import ScenarioBlueprintRepository

BLUEPRINT_PATH = Path(__file__).resolve().parents[1] / "scenario_blueprint.date_route.json"


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        runtime_event = getattr(record, "runtime_event", None)
        if runtime_event is not None:
            self.events.append(dict(runtime_event))


def test_pair_flow_emits_runtime_events_across_happy_path(tmp_path: Path) -> None:
    asyncio.run(_test_pair_flow_emits_runtime_events_across_happy_path(tmp_path))


def test_runtime_logs_generation_fallback_status(tmp_path: Path) -> None:
    asyncio.run(_test_runtime_logs_generation_fallback_status(tmp_path))


async def _test_pair_flow_emits_runtime_events_across_happy_path(tmp_path: Path) -> None:
    repository = await _make_repository(tmp_path / "runtime_events.db")
    blueprints = ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH})
    logger = logging.getLogger("tests.runtime_events")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = _ListHandler()
    logger.addHandler(handler)
    event_logger = RuntimeEventLogger(logger)

    runtime_service = PairScenarioRuntimeService(
        repository,
        blueprints,
        event_logger=event_logger,
        llm_client=LLMServiceClient(
            transport=lambda _prompt: json.dumps(
                {
                    "intro_text": "Событие генерации записало русское вступление.",
                    "questions": ["Какой формат тебе ближе?", "Что сразу создаёт лёгкость?"],
                    "transition_text": "Событие генерации записало русский переход.",
                }
            )
        ),
    )
    service = PairFlowApiService(
        repository=repository,
        runtime_service=runtime_service,
        blueprint_repository=blueprints,
        event_logger=event_logger,
    )

    create_response = await service.create_session(display_name="Alex")
    session_id = create_response.state.session.id
    participant_a_id = create_response.access.id

    join_response = await service.join_session(session_id, display_name="Sam")
    participant_b_id = join_response.access.id

    state = join_response.state
    assert state.run is not None
    run_id = state.run.id

    while state.current_scene is not None:
        scene_key = state.current_scene.key
        answer_a = "same-answer" if scene_key == "scene_02_direction" else f"{scene_key}-a"
        answer_b = "same-answer" if scene_key == "scene_02_direction" else f"{scene_key}-b"

        await service.submit_answer(
            session_id=session_id,
            participant_id=participant_a_id,
            content_text=answer_a,
        )
        result = await service.submit_answer(
            session_id=session_id,
            participant_id=participant_b_id,
            content_text=answer_b,
        )
        state = result.state
        if result.run_completed:
            break

    event_names = [event["event_name"] for event in handler.events]
    assert RuntimeEventName.SESSION_CREATED in event_names
    assert event_names.count(RuntimeEventName.PARTICIPANT_JOINED) == 2
    assert RuntimeEventName.SCENARIO_RUN_STARTED in event_names
    assert RuntimeEventName.SCENE_GENERATION_REQUESTED in event_names
    assert RuntimeEventName.SCENE_GENERATION_COMPLETED in event_names
    assert RuntimeEventName.SCENE_ACTIVATED in event_names
    assert RuntimeEventName.QUESTION_DELIVERED in event_names
    assert RuntimeEventName.ANSWER_SUBMITTED in event_names
    assert RuntimeEventName.WAITING_FOR_SECOND_ANSWER in event_names
    assert RuntimeEventName.ANSWERS_REVEALED in event_names
    assert RuntimeEventName.SCENE_COMPLETED in event_names
    assert RuntimeEventName.BRANCH_SELECTED in event_names
    assert RuntimeEventName.RUN_COMPLETED in event_names

    run_start_event = next(
        event
        for event in handler.events
        if event["event_name"] == RuntimeEventName.SCENARIO_RUN_STARTED
    )
    assert run_start_event["session_id"] == session_id
    assert run_start_event["scenario_run_id"] == run_id
    assert run_start_event["timestamp"]

    waiting_event = next(
        event
        for event in handler.events
        if event["event_name"] == RuntimeEventName.WAITING_FOR_SECOND_ANSWER
    )
    assert waiting_event["scene_id"] is not None
    assert waiting_event["metadata"]["answers_submitted_count"] == 1

    reveal_event = next(
        event
        for event in handler.events
        if event["event_name"] == RuntimeEventName.ANSWERS_REVEALED
    )
    assert reveal_event["metadata"]["answers_submitted_count"] == 2

    branch_event = next(
        event for event in handler.events if event["event_name"] == RuntimeEventName.BRANCH_SELECTED
    )
    assert "branch_reason" in branch_event["metadata"]

    generation_event = next(
        event
        for event in handler.events
        if event["event_name"] == RuntimeEventName.SCENE_GENERATION_COMPLETED
    )
    assert generation_event["metadata"]["used_fallback"] is False

    runtime_errors = [
        event for event in handler.events if event["event_name"] == RuntimeEventName.RUNTIME_ERROR
    ]
    assert runtime_errors == []


async def _test_runtime_logs_generation_fallback_status(tmp_path: Path) -> None:
    repository = await _make_repository(tmp_path / "runtime_generation_fallback_events.db")
    blueprints = ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH})
    logger = logging.getLogger("tests.runtime_generation_fallback_events")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = _ListHandler()
    logger.addHandler(handler)
    event_logger = RuntimeEventLogger(logger)

    runtime_service = PairScenarioRuntimeService(
        repository,
        blueprints,
        event_logger=event_logger,
        llm_client=LLMServiceClient(transport=lambda _prompt: "not-json"),
    )

    session = await repository.create_session(scenario_key="date_route")
    await repository.add_session_participant(session_id=session.id, slot=1, status="active")
    await repository.add_session_participant(session_id=session.id, slot=2, status="active")

    await runtime_service.start_run(session.id)

    generation_event = next(
        event
        for event in handler.events
        if event["event_name"] == RuntimeEventName.SCENE_GENERATION_COMPLETED
    )
    assert generation_event["metadata"]["used_fallback"] is True
    assert generation_event["metadata"]["validation_error"] is not None


async def _make_repository(db_path: Path) -> SqlAlchemyScenarioRuntimeRepository:
    engine = make_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return SqlAlchemyScenarioRuntimeRepository(session_factory)
