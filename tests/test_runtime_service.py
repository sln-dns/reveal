from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from idea_check_backend.llm_service.client import LLMServiceClient
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


def test_runtime_service_falls_back_when_llm_response_is_invalid(tmp_path: Path) -> None:
    asyncio.run(_test_runtime_service_falls_back_when_llm_response_is_invalid(tmp_path))


def test_runtime_service_generates_per_player_summary_on_completion(tmp_path: Path) -> None:
    asyncio.run(_test_runtime_service_generates_per_player_summary_on_completion(tmp_path))


def test_runtime_service_completes_run_even_when_summary_generation_falls_back(
    tmp_path: Path,
) -> None:
    asyncio.run(_test_runtime_service_completes_run_even_when_summary_generation_falls_back(tmp_path))


async def _test_runtime_service_executes_pair_flow_and_completes_run(tmp_path: Path) -> None:
    repository = await _make_repository(tmp_path / "runtime_service.db")
    llm_client = LLMServiceClient(
        transport=lambda _prompt: json.dumps(
            {
                "intro_text": "Рантайм вернул русское вступление.",
                "questions": [
                    "Что тебе ближе для такого вечера: прогулка, бар, уютный угол или свой вариант?",
                    "С чего тебе проще начать: с шутки, с простого вопроса, с наблюдения вокруг или свой вариант?",
                ],
                "transition_text": "Рантайм вернул русский переход.",
            }
        )
    )
    service = PairScenarioRuntimeService(
        repository,
        ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH}),
        llm_client=llm_client,
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
    assert (
        started_state.active_scene.scene_instance.generated_content["intro_text"]
        == "Рантайм вернул русское вступление."
    )
    assert (
        started_state.active_scene.scene_instance.generated_content["transition_text"]
        == "Рантайм вернул русский переход."
    )
    assert started_state.active_scene.scene_instance.generated_content["used_fallback"] is False
    assert len(started_state.active_scene.questions) == 2
    assert (
        started_state.active_scene.questions[0].prompt_text
        == "Что тебе ближе для такого вечера: прогулка, бар, уютный угол или свой вариант?"
    )
    assert (
        started_state.active_scene.questions[1].prompt_text
        == "Что тебе ближе для такого вечера: прогулка, бар, уютный угол или свой вариант?"
    )
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
    assert (
        second_answer_result.state.active_scene.scene_instance.generated_content["generation_payload"][
            "previous_answers_summary"
        ]
        == "участник_1: Quiet cafe | участник_2: Riverside walk"
    )

    completed_first_scene = await repository.get_scene_instance(first_scene_id)
    assert completed_first_scene is not None
    assert completed_first_scene.status == SceneStatus.COMPLETED
    assert completed_first_scene.state_payload["revealed"] is True

    first_scene_questions = await repository.list_question_instances_for_scene(first_scene_id)
    assert all(
        question.state_payload["reveal_available"] is True
        for question in first_scene_questions
    )
    assert all(
        question.prompt_payload["answer_format"] == "hybrid_choice_plus_text"
        for question in first_scene_questions
    )
    assert all(
        question.prompt_payload["custom_answer_label"] == "свой вариант"
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


async def _test_runtime_service_falls_back_when_llm_response_is_invalid(tmp_path: Path) -> None:
    repository = await _make_repository(tmp_path / "runtime_service_fallback.db")
    service = PairScenarioRuntimeService(
        repository,
        ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH}),
        llm_client=LLMServiceClient(transport=lambda _prompt: "not-json"),
    )

    session = await repository.create_session(scenario_key="date_route")
    participant_a = await repository.add_session_participant(
        session_id=session.id,
        slot=1,
        status=ParticipantStatus.ACTIVE,
    )
    participant_b = await repository.add_session_participant(
        session_id=session.id,
        slot=2,
        status=ParticipantStatus.ACTIVE,
    )

    started_state = await service.start_run(session.id)

    assert started_state.active_scene is not None
    generated_content = started_state.active_scene.scene_instance.generated_content
    assert generated_content["used_fallback"] is True
    assert generated_content["intro_text"]
    assert generated_content["questions"] == [
        "Какой вайб для такого вечера тебе ближе: лёгкий флирт, спокойный уют, немного игры или свой вариант?",
        "С чего тебе легче начать такое приключение: с шутки, с простого вопроса, с наблюдения вокруг или со своего варианта?",
    ]
    assert generated_content["generation_log"]["used_fallback"] is True
    assert generated_content["generation_log"]["validation_error"] is not None
    assert (
        started_state.active_scene.questions[0].prompt_text == generated_content["questions"][0]
    )
    assert (
        started_state.active_scene.questions[1].prompt_text == generated_content["questions"][0]
    )


async def _test_runtime_service_generates_per_player_summary_on_completion(
    tmp_path: Path,
) -> None:
    repository = await _make_repository(tmp_path / "runtime_service_summary.db")
    service = PairScenarioRuntimeService(
        repository,
        ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH}),
        llm_client=LLMServiceClient(
            transport=lambda _prompt: json.dumps(
                {
                    "intro_text": "Рантайм вернул русское вступление.",
                    "questions": ["Что тебе сразу понравилось?", "Какой темп тебе ближе?"],
                    "transition_text": "Рантайм вернул русский переход.",
                }
            )
        ),
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

    state = await service.start_run(session.id)
    while state.active_scene is not None:
        scene_key = state.active_scene.scene_instance.scene_key
        await service.submit_answer(
            run_id=state.run.id,
            participant_id=participant_a.id,
            content_text=f"{scene_key} quiet cafe and long walk",
        )
        result = await service.submit_answer(
            run_id=state.run.id,
            participant_id=participant_b.id,
            content_text=f"{scene_key} playful adventure and jokes",
        )
        if result.run_completed:
            final_state = result.state
            break
        state = result.state
    else:
        raise AssertionError("Runtime should complete the scenario run")

    assert final_state.run.status == RunStatus.COMPLETED
    assert final_state.active_scene is None
    assert len(final_state.summaries) == 2

    stored_summaries = await repository.list_run_summaries(final_state.run.id)
    assert len(stored_summaries) == 2
    assert {item.content_payload["recipient_participant_id"] for item in stored_summaries} == {
        participant_a.id,
        participant_b.id,
    }
    assert {item.content_payload["subject_participant_id"] for item in stored_summaries} == {
        participant_a.id,
        participant_b.id,
    }
    assert all(item.kind == "run" for item in stored_summaries)
    assert all(item.content_payload["summary_tone"] == "warm_observational" for item in stored_summaries)
    assert all(
        item.content_payload["forbidden_summary_styles"]
        == ["clinical_psychology", "compatibility_score_only", "judgmental_language"]
        for item in stored_summaries
    )
    assert any("В реальном разговоре можно продолжить" in item.content_text for item in stored_summaries)

    completed_run = await repository.get_scenario_run(final_state.run.id)
    assert completed_run is not None
    summary_context = completed_run.generated_content["summary_context"]
    assert summary_context["summary_focus"] == [
        "other_person_preferences",
        "other_person_vibe",
        "conversation_topics_for_real_meeting",
    ]
    assert len(summary_context["participants"]) == 2


async def _test_runtime_service_completes_run_even_when_summary_generation_falls_back(
    tmp_path: Path,
) -> None:
    repository = await _make_repository(tmp_path / "runtime_service_summary_fallback.db")
    service = PairScenarioRuntimeService(
        repository,
        ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH}),
        llm_client=LLMServiceClient(
            transport=lambda _prompt: json.dumps(
                {
                    "intro_text": "Рантайм вернул русское вступление.",
                    "questions": ["Что тебе сразу понравилось?", "Какой темп тебе ближе?"],
                    "transition_text": "Рантайм вернул русский переход.",
                }
            )
        ),
        summary_generator=lambda _context, _recipient: (_ for _ in ()).throw(
            ValueError("summary generation failed")
        ),
    )

    session = await repository.create_session(scenario_key="date_route")
    participant_a = await repository.add_session_participant(
        session_id=session.id,
        slot=1,
        status=ParticipantStatus.ACTIVE,
    )
    participant_b = await repository.add_session_participant(
        session_id=session.id,
        slot=2,
        status=ParticipantStatus.ACTIVE,
    )

    state = await service.start_run(session.id)
    while state.active_scene is not None:
        await service.submit_answer(
            run_id=state.run.id,
            participant_id=participant_a.id,
            content_text="quiet cafe",
        )
        result = await service.submit_answer(
            run_id=state.run.id,
            participant_id=participant_b.id,
            content_text="riverside walk",
        )
        if result.run_completed:
            final_state = result.state
            break
        state = result.state
    else:
        raise AssertionError("Runtime should complete the scenario run")

    assert final_state.run.status == RunStatus.COMPLETED
    summaries = await repository.list_run_summaries(final_state.run.id)
    assert len(summaries) == 2
    assert all(item.content_payload["used_fallback"] is True for item in summaries)


async def _make_repository(db_path: Path) -> SqlAlchemyScenarioRuntimeRepository:
    engine = make_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return SqlAlchemyScenarioRuntimeRepository(session_factory)
