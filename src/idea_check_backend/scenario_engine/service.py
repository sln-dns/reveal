from idea_check_backend.llm_service.client import LLMServiceClient
from idea_check_backend.persistence.repository import ScenarioRepository
from idea_check_backend.shared_types.scenario import ScenarioDraft, SceneGenerationPayload
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
        blueprint = self.get_blueprint(scenario_id)
        generated_scenes = []
        generation_logs = []
        prompt = ""

        for scene in blueprint.scene_flow:
            if not self._llm_client.supports_scene(scene.scene_id):
                continue

            payload = SceneGenerationPayload(
                scene_id=scene.scene_id,
                scene_type=scene.scene_type,
                scene_title=scene.title,
                scene_purpose=scene.purpose,
                psychological_goal=scene.psychological_goal,
                ladder_stages=scene.ladder_stages,
                allowed_question_families=scene.allowed_question_families,
                forbidden_question_families=scene.forbidden_question_families,
                question_templates=scene.question_templates,
                question_count_target=scene.question_count_target,
                transition_goal=scene.transition_goal,
                selected_world=blueprint.world_setup.preset_world_ids[0],
                selected_tone=blueprint.world_setup.allowed_tones[0],
                product_goal=blueprint.product_goal,
                experience_principles=blueprint.experience_principles,
                max_answer_length_chars=blueprint.question_policy.max_answer_length_chars,
            )
            result = self._llm_client.generate_scene(payload)
            generated_scenes.append(result.generation)
            generation_logs.append(result.log)
            if not prompt:
                prompt = result.log.prompt

        draft = ScenarioDraft(
            id=scenario_id,
            prompt=prompt,
            scenes=generated_scenes,
            generation_logs=generation_logs,
        )
        self._repository.save(draft)
        return draft
