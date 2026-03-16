from idea_check_backend.llm_service.client import LLMServiceClient
from idea_check_backend.persistence.repository import ScenarioRepository
from idea_check_backend.shared_types.scenario import ScenarioDraft


class ScenarioEngine:
    def __init__(
        self,
        repository: ScenarioRepository,
        llm_client: LLMServiceClient,
    ) -> None:
        self._repository = repository
        self._llm_client = llm_client

    def bootstrap(self, scenario_id: str) -> ScenarioDraft:
        prompt = self._llm_client.build_prompt(scenario_id)
        draft = ScenarioDraft(id=scenario_id, prompt=prompt)
        self._repository.save(draft)
        return draft
