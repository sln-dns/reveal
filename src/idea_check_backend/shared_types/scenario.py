from pydantic import BaseModel, Field


class SceneGenerationPayload(BaseModel):
    scene_id: str
    scene_type: str
    scene_title: str | None = None
    scene_purpose: str
    psychological_goal: str
    ladder_stages: list[str]
    allowed_question_families: list[str]
    forbidden_question_families: list[str]
    question_templates: list[str]
    question_count_target: int
    transition_goal: str
    selected_world: str
    selected_tone: str
    product_goal: str
    experience_principles: list[str]
    max_answer_length_chars: int
    previous_answers_summary: str | None = None
    branching_context: str | None = None


class SceneGeneration(BaseModel):
    scene_id: str
    intro_text: str
    questions: list[str] = Field(min_length=1, max_length=3)
    transition_text: str
    used_fallback: bool = False


class SceneGenerationLog(BaseModel):
    scene_id: str
    provider: str
    model: str
    prompt: str
    raw_response: str
    validation_error: str | None = None
    used_fallback: bool = False


class ScenarioDraft(BaseModel):
    id: str
    prompt: str
    scenes: list[SceneGeneration] = Field(default_factory=list)
    generation_logs: list[SceneGenerationLog] = Field(default_factory=list)
