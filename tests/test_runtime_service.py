from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from idea_check_backend.persistence.db import make_async_engine
from idea_check_backend.persistence.models import (
    Base,
    ParticipantStatus,
    RunStatus,
    SceneStatus,
)
from idea_check_backend.persistence.repository import SqlAlchemyScenarioRuntimeRepository
from idea_check_backend.runtime_service import (
    InvalidAnswerSubmissionError,
    PairScenarioRuntimeService,
)
from idea_check_backend.scenario_engine.blueprint_loader import ScenarioBlueprintRepository

BLUEPRINT_PATH = Path(__file__).resolve().parents[1] / "scenario_blueprint.date_route.json"


def test_runtime_service_executes_pair_flow_and_completes_run(tmp_path: Path) -> None:
    asyncio.run(_test_runtime_service_executes_pair_flow_and_completes_run(tmp_path))


def test_runtime_service_rejects_duplicate_answer(tmp_path: Path) -> None:
    asyncio.run(_test_runtime_service_rejects_duplicate_answer(tmp_path))


async def _test_runtime_service_executes_pair_flow_and_completes_run(tmp_path: Path) -> None:
    repository = await _make_repository(tmp_path / "runtime_service.db")
    service = PairScenarioRuntimeService(
        repository,
        ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH}),
    )

    session = await repository.create_session(scenario_key="date_route")
    participant_a = await repository.add_session_participant(
        session_id=session.id,
        slot=1,
        display_name="Alex",
        status=ParticipantStatus.ACTIVE,
    )
    participant_b = await repository.add_session_participant(
        session_id=session.id,
        slot=2,
        display_name="Sam",
        status=ParticipantStatus.ACTIVE,
    )

    started_state = await service.start_run(session.id)

    assert started_state.run.status == RunStatus.WAITING_FOR_ANSWERS
    assert started_state.run.current_scene_key == "scene_01_intro"
    assert started_state.active_scene is not None
    assert started_state.active_scene.scene_instance.scene_key == "scene_01_intro"
    assert started_state.active_scene.phase == "collecting_answers"
    assert len(started_state.active_scene.questions) == 2
    assert all(question.answer_text is None for question in started_state.active_scene.questions)

    run_id = started_state.run.id
    first_scene_id = started_state.active_scene.scene_instance.id

    first_answer_result = await service.submit_answer(
        run_id=run_id,
        participant_id=participant_a.id,
        content_text="Quiet cafe",
    )

    assert first_answer_result.reveal_triggered is False
    assert first_answer_result.advanced_to_next_scene is False
    assert first_answer_result.run_completed is False
    assert first_answer_result.state.active_scene is not None
    assert first_answer_result.state.active_scene.scene_instance.id == first_scene_id
    assert first_answer_result.state.active_scene.phase == "waiting_for_partner"
    assert all(
        question.answer_text is None
        for question in first_answer_result.state.active_scene.questions
    )

    second_answer_result = await service.submit_answer(
        run_id=run_id,
        participant_id=participant_b.id,
        content_text="Riverside walk",
    )

    assert second_answer_result.reveal_triggered is True
    assert second_answer_result.advanced_to_next_scene is True
    assert second_answer_result.run_completed is False
    assert second_answer_result.state.active_scene is not None
    assert second_answer_result.state.active_scene.scene_instance.scene_key == "scene_02_direction"
    assert second_answer_result.state.active_scene.phase == "collecting_answers"

    completed_first_scene = await repository.get_scene_instance(first_scene_id)
    assert completed_first_scene is not None
    assert completed_first_scene.status == SceneStatus.COMPLETED
    assert completed_first_scene.state_payload["revealed"] is True

    first_scene_questions = await repository.list_question_instances_for_scene(first_scene_id)
    assert all(
        question.state_payload["reveal_available"] is True
        for question in first_scene_questions
    )

    revealed_answers = await repository.list_scene_answers_for_reveal(first_scene_id)
    assert [answer.content_text for answer in revealed_answers] == ["Quiet cafe", "Riverside walk"]

    state = second_answer_result.state
    while state.active_scene is not None:
        scene_key = state.active_scene.scene_instance.scene_key
        answer_a = "same-answer" if scene_key == "scene_02_direction" else f"{scene_key}-a"
        answer_b = "same-answer" if scene_key == "scene_02_direction" else f"{scene_key}-b"

        await service.submit_answer(
            run_id=run_id,
            participant_id=participant_a.id,
            content_text=answer_a,
        )
        result = await service.submit_answer(
            run_id=run_id,
            participant_id=participant_b.id,
            content_text=answer_b,
        )

        if result.run_completed:
            final_run = await repository.get_scenario_run(run_id)
            final_session = await repository.get_session(session.id)
            assert final_run is not None
            assert final_run.status == RunStatus.COMPLETED
            assert final_run.runtime_state["phase"] == "completed"
            assert final_session is not None
            assert final_session.status == "completed"
            break

        assert result.state.active_scene is not None
        state = result.state
    else:
        raise AssertionError("Runtime should complete the scenario run")


async def _test_runtime_service_rejects_duplicate_answer(tmp_path: Path) -> None:
    repository = await _make_repository(tmp_path / "runtime_service_negative.db")
    service = PairScenarioRuntimeService(
        repository,
        ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH}),
    )

    session = await repository.create_session(scenario_key="date_route")
    participant = await repository.add_session_participant(
        session_id=session.id,
        slot=1,
        status=ParticipantStatus.ACTIVE,
    )
    await repository.add_session_participant(
        session_id=session.id,
        slot=2,
        status=ParticipantStatus.ACTIVE,
    )

    started_state = await service.start_run(session.id)

    await service.submit_answer(
        run_id=started_state.run.id,
        participant_id=participant.id,
        content_text="First answer",
    )

    try:
        await service.submit_answer(
            run_id=started_state.run.id,
            participant_id=participant.id,
            content_text="Duplicate answer",
        )
    except InvalidAnswerSubmissionError as error:
        assert "already answered" in str(error)
    else:
        raise AssertionError("Expected duplicate answer to be rejected")


async def _make_repository(db_path: Path) -> SqlAlchemyScenarioRuntimeRepository:
    engine = make_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return SqlAlchemyScenarioRuntimeRepository(session_factory)
