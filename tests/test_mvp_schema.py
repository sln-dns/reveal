from __future__ import annotations

import asyncio
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from alembic import command
from idea_check_backend.persistence.db import make_async_engine
from idea_check_backend.persistence.models import (
    Answer,
    QuestionInstance,
    ScenarioRun,
    SceneInstance,
    Session,
    SessionParticipant,
    Summary,
)


def test_alembic_upgrade_creates_mvp_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "schema.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    assert set(inspector.get_table_names()) >= {
        "answer",
        "question_instance",
        "scenario_run",
        "scene_instance",
        "session",
        "session_participant",
        "summary",
    }


def test_async_models_persist_runtime_graph(tmp_path: Path) -> None:
    asyncio.run(_persist_runtime_graph(tmp_path))


async def _persist_runtime_graph(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")

    engine = make_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db_session:
        session = Session(scenario_key="date_route", status="active")
        participant_a = SessionParticipant(slot=1, role="lead", status="active")
        participant_b = SessionParticipant(slot=2, role="partner", status="active")
        session.participants.extend([participant_a, participant_b])

        run = ScenarioRun(scenario_key="date_route", scenario_version="v1", status="active")
        session.scenario_runs.append(run)

        scene = SceneInstance(scene_key="intro", position=1, status="active")
        run.scene_instances.append(scene)

        question_a = QuestionInstance(
            participant=participant_a,
            question_key="intro_q1",
            position=1,
            status="delivered",
            prompt_text="First question",
        )
        question_b = QuestionInstance(
            participant=participant_b,
            question_key="intro_q2",
            position=2,
            status="delivered",
            prompt_text="Second question",
        )
        scene.question_instances.extend([question_a, question_b])

        question_a.answers.append(
            Answer(participant=participant_a, content_text="Answer from participant A")
        )
        question_b.answers.append(
            Answer(participant=participant_b, content_text="Answer from participant B")
        )

        run.summaries.append(
            Summary(kind="run", content_text="Both participants completed the intro.")
        )

        db_session.add(session)
        await db_session.commit()

    async with session_factory() as db_session:
        participant_count = await db_session.scalar(
            select(func.count()).select_from(SessionParticipant)
        )
        run_count = await db_session.scalar(select(func.count()).select_from(ScenarioRun))
        question_count = await db_session.scalar(
            select(func.count()).select_from(QuestionInstance)
        )
        answer_count = await db_session.scalar(select(func.count()).select_from(Answer))
        summary_count = await db_session.scalar(select(func.count()).select_from(Summary))

        assert participant_count == 2
        assert run_count == 1
        assert question_count == 2
        assert answer_count == 2
        assert summary_count == 1

    await engine.dispose()
