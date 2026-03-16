class LLMServiceClient:
    def build_prompt(self, scenario_id: str) -> str:
        return f"Generate a draft for scenario '{scenario_id}'."
