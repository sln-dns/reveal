from __future__ import annotations

import json
from pathlib import Path

from idea_check_backend.shared_types.scenario_blueprint import ScenarioBlueprint

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BLUEPRINT_PATHS = {
    "date_route": REPOSITORY_ROOT / "scenario_blueprint.date_route.json",
}


class ScenarioBlueprintRepository:
    def __init__(self, blueprint_paths: dict[str, Path] | None = None) -> None:
        self._blueprint_paths = blueprint_paths or DEFAULT_BLUEPRINT_PATHS

    def get(self, scenario_key: str) -> ScenarioBlueprint:
        blueprint_path = self._blueprint_paths.get(scenario_key)
        if blueprint_path is None:
            raise KeyError(f"Unsupported scenario blueprint '{scenario_key}'")
        return load_scenario_blueprint(blueprint_path)


def load_scenario_blueprint(path: Path) -> ScenarioBlueprint:
    with path.open("r", encoding="utf-8") as blueprint_file:
        raw_blueprint = json.load(blueprint_file)
    return ScenarioBlueprint.model_validate(raw_blueprint)
