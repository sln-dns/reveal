from idea_check_backend.shared_types.scenario import ScenarioDraft


class ScenarioRepository:
    def __init__(self) -> None:
        self._items: dict[str, ScenarioDraft] = {}

    def save(self, draft: ScenarioDraft) -> None:
        self._items[draft.id] = draft

    def get(self, scenario_id: str) -> ScenarioDraft | None:
        return self._items.get(scenario_id)
