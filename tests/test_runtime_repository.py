from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from idea_check_backend.persistence.db import make_async_engine
from idea_check_backend.persistence.models import (
    Base,
    ParticipantStatus,
    QuestionStatus,
    RunStatus,
    SceneStatus,
    SessionStatus,
    SummaryKind,
)
from idea_check_backend.persistence.repository import SqlAlchemyScenarioRuntimeRepository


def test_runtime_repository_persists_runtime_graph_across_instances(tmp_path: Path) -> None:
    asyncio.run(_test_runtime_repository_persists_runtime_graph_across_instances(tmp_path))


def test_runtime_repository_updates_statuses_and_runtime_state(tmp_path: Path) -> None:
    asyncio.run(_test_runtime_repository_updates_statuses_and_runtime_state(tmp_path))


async def _test_runtime_repository_persists_runtime_graph_across_instances(
    tmp_path: Path,
) -> None:
    repository = await _make_repository(tmp_path / "runtime_repo.db")

    session = await repository.create_session(
        scenario_key="date_route",
        status=SessionStatus.ACTIVE,
        lifecycle_state={"step": "bootstrapped"},
    )
    participant_a = await repository.add_session_participant(
        session_id=session.id,
        slot=1,
        role="lead",
        display_name="Alex",
        status=ParticipantStatus.ACTIVE,
    )
    participant_b = await repository.add_session_participant(
        session_id=session.id,
        slot=2,
        role="partner",
        display_name="Sam",
        status=ParticipantStatus.ACTIVE,
    )
    run = await repository.create_scenario_run(
        session_id=session.id,
        scenario_key="date_route",
        status=RunStatus.ACTIVE,
        runtime_state={"scene_index": 0},
    )
    scene = await repository.create_scene_instance(
        scenario_run_id=run.id,
        scene_key="scene_01_intro",
        position=1,
    )
    active_scene = await repository.activate_scene_instance(scene.id)
    question_a = await repository.create_question_instance(
        scene_instance_id=scene.id,
        participant_id=participant_a.id,
        question_key="intro_q1",
        position=1,
        status=QuestionStatus.DELIVERED,
        prompt_text="What feels easy tonight?",
    )
    question_b = await repository.create_question_instance(
        scene_instance_id=scene.id,
        participant_id=participant_b.id,
        question_key="intro_q2",
        position=2,
        status=QuestionStatus.DELIVERED,
        prompt_text="What kind of pace do you want?",
    )

    await repository.save_answer(
        question_instance_id=question_a.id,
        participant_id=participant_a.id,
        content_text="Slow and relaxed.",
        content_payload={"mood": "slow"},
    )
    await repository.save_answer(
        question_instance_id=question_b.id,
        participant_id=participant_b.id,
        content_text="Playful, but not loud.",
        content_payload={"mood": "playful"},
    )
    summary = await repository.save_summary(
        scenario_run_id=run.id,
        scene_instance_id=scene.id,
        kind=SummaryKind.SCENE,
        content_text="Both participants aligned on a low-pressure vibe.",
        content_payload={"alignment": "low_pressure"},
    )

    reloaded_repository = await _make_repository(tmp_path / "runtime_repo.db")
    reloaded_session = await reloaded_repository.get_session(session.id)
    reloaded_run = await reloaded_repository.get_scenario_run(run.id)
    reloaded_scene = await reloaded_repository.get_active_scene_for_run(run.id)
    reveal_answers = await reloaded_repository.list_scene_answers_for_reveal(scene.id)
    summaries = await reloaded_repository.list_run_summaries(run.id)

    assert reloaded_session is not None
    assert reloaded_session.lifecycle_state == {"step": "bootstrapped"}
    assert reloaded_run is not None
    assert reloaded_run.current_scene_key == "scene_01_intro"
    assert active_scene.status == SceneStatus.ACTIVE
    assert reloaded_scene is not None
    assert reloaded_scene.id == scene.id
    assert [answer.content_text for answer in reveal_answers] == [
        "Slow and relaxed.",
        "Playful, but not loud.",
    ]
    assert [answer.content_payload["mood"] for answer in reveal_answers] == ["slow", "playful"]
    assert summaries == [summary]


async def _test_runtime_repository_updates_statuses_and_runtime_state(
    tmp_path: Path,
) -> None:
    repository = await _make_repository(tmp_path / "runtime_state_repo.db")

    session = await repository.create_session(scenario_key="date_route")
    participant = await repository.add_session_participant(session_id=session.id, slot=1)
    run = await repository.create_scenario_run(session_id=session.id, scenario_key="date_route")
    scene = await repository.create_scene_instance(
        scenario_run_id=run.id,
        scene_key="scene_02_direction",
        position=2,
    )
    question = await repository.create_question_instance(
        scene_instance_id=scene.id,
        participant_id=participant.id,
        question_key="direction_q1",
        position=1,
    )

    updated_session = await repository.update_session(
        session.id,
        status=SessionStatus.ACTIVE,
        metadata_payload={"entrypoint": "api"},
    )
    updated_participant = await repository.update_session_participant(
        participant.id,
        status=ParticipantStatus.COMPLETED,
        generated_profile={"archetype": "listener"},
    )
    updated_run = await repository.update_scenario_run(
        run.id,
        status=RunStatus.WAITING_FOR_ANSWERS,
        current_scene_key=scene.scene_key,
    )
    runtime_state = await repository.update_runtime_state(
        run.id,
        {"scene_index": 2, "reveal_ready": True},
    )
    updated_scene = await repository.update_scene_instance(
        scene.id,
        status=SceneStatus.COMPLETED,
        state_payload={"revealed": True},
    )
    updated_question = await repository.update_question_instance(
        question.id,
        status=QuestionStatus.ANSWERED,
        answered_at=question.created_at,
    )

    assert updated_session.status == SessionStatus.ACTIVE
    assert updated_session.metadata_payload == {"entrypoint": "api"}
    assert updated_participant.status == ParticipantStatus.COMPLETED
    assert updated_participant.generated_profile == {"archetype": "listener"}
    assert updated_run.status == RunStatus.WAITING_FOR_ANSWERS
    assert updated_run.current_scene_key == "scene_02_direction"
    assert runtime_state.runtime_state == {"scene_index": 2, "reveal_ready": True}
    assert await repository.get_runtime_state(run.id) == {"scene_index": 2, "reveal_ready": True}
    assert updated_scene.status == SceneStatus.COMPLETED
    assert updated_scene.state_payload == {"revealed": True}
    assert updated_question.status == QuestionStatus.ANSWERED


async def _make_repository(db_path: Path) -> SqlAlchemyScenarioRuntimeRepository:
    engine = make_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return SqlAlchemyScenarioRuntimeRepository(session_factory)
