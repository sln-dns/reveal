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

BLUEPRINT_PATH = Path(__file__).resolve().parents[1] / "scenario_blueprint.date_route.json"


def test_load_date_route_blueprint_returns_typed_domain_object() -> None:
    blueprint = load_scenario_blueprint(BLUEPRINT_PATH)

    assert blueprint.scenario_type == "date_route"
    assert blueprint.question_policy.questions_per_scene_min == 2
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


def _read_blueprint_payload() -> dict:
    return json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))


def _write_payload(tmp_path: Path, payload: dict) -> Path:
    broken_path = tmp_path / "scenario_blueprint.invalid.json"
    broken_path.write_text(json.dumps(payload), encoding="utf-8")
    return broken_path
