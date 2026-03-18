from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from idea_check_backend.llm_service.client import LLMServiceClient
from idea_check_backend.persistence.repository import ScenarioRepository
from idea_check_backend.scenario_engine.blueprint_loader import (
    ScenarioBlueprintRepository,
    load_scenario_blueprint,
)
from idea_check_backend.scenario_engine.service import ScenarioEngine
from idea_check_backend.shared_types.scenario import SceneGenerationPayload

BLUEPRINT_PATH = Path(__file__).resolve().parents[1] / "scenario_blueprint.date_route.json"


def test_load_date_route_blueprint_returns_typed_domain_object() -> None:
    blueprint = load_scenario_blueprint(BLUEPRINT_PATH)

    assert blueprint.scenario_type == "date_route"
    assert blueprint.question_policy.questions_per_scene_min == 2
    assert blueprint.question_policy.default_answer_format == "hybrid_choice_plus_text"
    assert blueprint.question_policy.preferred_question_style == "fast_choice_with_optional_custom_text"
    assert blueprint.question_policy.custom_answer_label == "свой вариант"
    assert blueprint.branching_policy.fallback_branch_type == "neutral_third_option"
    assert blueprint.scene_flow[1].branch_outcomes.if_difference == "scene_03_compromise"


def test_load_blueprint_rejects_unknown_branch_target(tmp_path: Path) -> None:
    payload = _read_blueprint_payload()
    payload["scene_flow"][0]["branch_outcomes"]["default_next_scene_id"] = "missing_scene"
    broken_path = _write_payload(tmp_path, payload)

    with pytest.raises(ValidationError, match="references unknown next scene"):
        load_scenario_blueprint(broken_path)


def test_load_blueprint_rejects_question_count_outside_policy(tmp_path: Path) -> None:
    payload = _read_blueprint_payload()
    payload["scene_flow"][0]["question_count_target"] = 99
    broken_path = _write_payload(tmp_path, payload)

    with pytest.raises(ValidationError, match="question_count_target must be within"):
        load_scenario_blueprint(broken_path)


def test_scenario_engine_returns_blueprint_domain_object() -> None:
    engine = ScenarioEngine(
        repository=ScenarioRepository(),
        llm_client=LLMServiceClient(),
        blueprint_repository=ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH}),
    )

    blueprint = engine.get_blueprint("date_route")

    assert blueprint.scenario_id == "date_route_mvp"
    assert blueprint.scene_flow[-1].branch_outcomes.end_scenario is True


def test_scenario_engine_bootstrap_generates_first_two_scenes() -> None:
    engine = ScenarioEngine(
        repository=ScenarioRepository(),
        llm_client=LLMServiceClient(),
        blueprint_repository=ScenarioBlueprintRepository({"date_route": BLUEPRINT_PATH}),
    )

    draft = engine.bootstrap("date_route")

    assert [scene.scene_id for scene in draft.scenes] == [
        "scene_01_intro",
        "scene_02_direction",
    ]
    assert all(scene.intro_text for scene in draft.scenes)
    assert all(1 <= len(scene.questions) <= 3 for scene in draft.scenes)
    assert all(log.prompt for log in draft.generation_logs)
    assert all(log.raw_response for log in draft.generation_logs)
    assert all(log.used_fallback is False for log in draft.generation_logs)


def test_llm_service_falls_back_when_model_returns_bad_format() -> None:
    client = LLMServiceClient(transport=lambda prompt: "not-json")

    result = client.generate_scene(
        SceneGenerationPayload(
            scene_id="scene_01_intro",
            scene_type="intro",
            scene_title="Старт маршрута",
            scene_purpose="Дать короткий контекст и запустить маршрут.",
            psychological_goal="Снизить напряжение и начать легко.",
            ladder_stages=["Разогрев", "Вкус"],
            allowed_question_families=["very_light_vibe"],
            forbidden_question_families=["self_analysis"],
            question_templates=[
                "Что тебе ближе для такого вечера: лёгкий флирт, спокойный уют, немного игры или свой вариант?",
                "С чего тебе легче начать: с шутки, с простого вопроса, с наблюдения вокруг или свой вариант?",
            ],
            question_count_target=2,
            transition_goal="Подвести игроков к более ясному направлению маршрута.",
            selected_world="evening_city",
            selected_tone="playful",
            product_goal="Помочь двум людям легко начать разговор.",
            experience_principles=["low_cognitive_load", "light_playful_tone"],
            max_answer_length_chars=180,
            default_answer_format="hybrid_choice_plus_text",
            allowed_answer_formats=["short_text", "single_choice", "hybrid_choice_plus_text"],
            preferred_question_style="fast_choice_with_optional_custom_text",
            preferred_option_count_min=3,
            preferred_option_count_max=4,
            allow_custom_answer_option=True,
            custom_answer_label="свой вариант",
            question_generation_rules=[
                "По умолчанию вопрос должен провоцировать быстрый выбор, а не длинное размышление.",
            ],
        )
    )

    assert result.generation.used_fallback is True
    assert result.generation.questions == [
        "Что тебе ближе для такого вечера: лёгкий флирт, спокойный уют, немного игры или свой вариант?",
        "С чего тебе легче начать: с шутки, с простого вопроса, с наблюдения вокруг или свой вариант?",
    ]
    assert result.log.used_fallback is True
    assert result.log.validation_error is not None
    assert result.log.raw_response == "not-json"


def _read_blueprint_payload() -> dict:
    return json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))


def _write_payload(tmp_path: Path, payload: dict) -> Path:
    broken_path = tmp_path / "scenario_blueprint.invalid.json"
    broken_path.write_text(json.dumps(payload), encoding="utf-8")
    return broken_path
