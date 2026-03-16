from idea_check_backend.llm_service.client import LLMServiceClient
from idea_check_backend.persistence.repository import ScenarioRepository
from idea_check_backend.shared_types.scenario import ScenarioDraft
from idea_check_backend.shared_types.scenario_blueprint import ScenarioBlueprint

from .blueprint_loader import ScenarioBlueprintRepository


class ScenarioEngine:
    def __init__(
        self,
        repository: ScenarioRepository,
        llm_client: LLMServiceClient,
        blueprint_repository: ScenarioBlueprintRepository | None = None,
    ) -> None:
        self._repository = repository
        self._llm_client = llm_client
        self._blueprint_repository = blueprint_repository or ScenarioBlueprintRepository()

    def get_blueprint(self, scenario_key: str) -> ScenarioBlueprint:
        return self._blueprint_repository.get(scenario_key)

    def bootstrap(self, scenario_id: str) -> ScenarioDraft:
        prompt = self._llm_client.build_prompt(scenario_id)
        draft = ScenarioDraft(id=scenario_id, prompt=prompt)
        self._repository.save(draft)
        return draft
