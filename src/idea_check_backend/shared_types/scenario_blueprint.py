from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerationArchitecture(BaseModel):
    engine_required_sections: list[str]
    prompt_required_sections: list[str]
    editorial_optional_sections: list[str]


class PsychologicalProgression(BaseModel):
    model: str
    stage_order: list[str]
    stage_purposes: dict[str, str]

    @model_validator(mode="after")
    def validate_stage_purposes(self) -> "PsychologicalProgression":
        missing_stages = [stage for stage in self.stage_order if stage not in self.stage_purposes]
        if missing_stages:
            raise ValueError(
                "psychological_progression.stage_purposes is missing entries for: "
                + ", ".join(missing_stages)
            )
        return self


class SessionModel(BaseModel):
    players_count: int = Field(ge=1)
    mode: str
    answer_reveal: str
    pause_resume_allowed: bool
    estimated_total_steps: int = Field(ge=1)
    estimated_scene_count: int = Field(ge=1)


class WorldSetup(BaseModel):
    selection_mode: str
    preset_world_ids: list[str]
    tone_mode: str
    allowed_tones: list[str]
    realism_mode: str


class ProgressionPolicy(BaseModel):
    unit: str
    show_progress_to_users: bool
    progress_label_template: str
    interruption_safe: bool


class QuestionPolicy(BaseModel):
    default_answer_format: str
    allowed_answer_formats: list[str]
    questions_per_scene_min: int = Field(ge=1)
    questions_per_scene_max: int = Field(ge=1)
    max_answer_length_chars: int = Field(ge=1)
    llm_interpretation_during_run: str
    direct_psychological_analysis: bool

    @model_validator(mode="after")
    def validate_range(self) -> "QuestionPolicy":
        if self.questions_per_scene_min > self.questions_per_scene_max:
            raise ValueError("questions_per_scene_min must be less than or equal to max")
        if self.default_answer_format not in self.allowed_answer_formats:
            raise ValueError("default_answer_format must be included in allowed_answer_formats")
        return self


class BranchingPolicy(BaseModel):
    difference_strategy: str
    match_strategy: str
    hard_blocking_on_difference: bool
    fallback_branch_type: str
    branching_inputs: list[str]


class SummaryPolicy(BaseModel):
    generate_summary: bool
    summary_per_player: bool
    summary_focus: list[str]
    summary_tone: str
    forbidden_summary_styles: list[str]


class BranchOutcomes(BaseModel):
    default_next_scene_id: str | None = None
    if_match: str | None = None
    if_difference: str | None = None
    end_scenario: bool = False

    @model_validator(mode="after")
    def validate_outcomes(self) -> "BranchOutcomes":
        has_transition = any(
            value is not None
            for value in (
                self.default_next_scene_id,
                self.if_match,
                self.if_difference,
            )
        )
        if self.end_scenario and has_transition:
            raise ValueError("end_scenario cannot be combined with next-scene transitions")
        if not self.end_scenario and not has_transition:
            raise ValueError("branch_outcomes must define a next scene or set end_scenario=true")
        return self


class SceneDefinition(BaseModel):
    scene_id: str
    scene_type: str
    psychological_stage: str
    title: str | None = None
    purpose: str
    ladder_stages: list[str]
    psychological_goal: str
    allowed_question_families: list[str]
    forbidden_question_families: list[str]
    question_count_target: int = Field(ge=1)
    entry_text_mode: str
    question_templates: list[str]
    transition_goal: str
    branch_outcomes: BranchOutcomes


class LLMGenerationContract(BaseModel):
    input_sections: list[str]
    output_sections: list[str]
    must_preserve: list[str]


class ScenarioBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    scenario_id: str
    scenario_name: str
    scenario_type: str
    status: Literal["draft", "active", "archived"]
    description: str
    product_goal: str
    generation_architecture: GenerationArchitecture
    experience_principles: list[str]
    psychological_progression: PsychologicalProgression
    session_model: SessionModel
    world_setup: WorldSetup
    progression: ProgressionPolicy
    scene_types: list[str]
    question_policy: QuestionPolicy
    branching_policy: BranchingPolicy
    summary_policy: SummaryPolicy
    scene_flow: list[SceneDefinition]
    llm_generation_contract: LLMGenerationContract
    future_extensions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scene_flow(self) -> "ScenarioBlueprint":
        scene_ids = [scene.scene_id for scene in self.scene_flow]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("scene_flow contains duplicate scene_id values")

        if self.session_model.estimated_scene_count > len(self.scene_flow):
            raise ValueError(
                "session_model.estimated_scene_count cannot exceed scene_flow length"
            )

        valid_scene_ids = set(scene_ids)
        valid_stage_ids = set(self.psychological_progression.stage_order)
        valid_scene_types = set(self.scene_types)

        for scene in self.scene_flow:
            if scene.scene_type not in valid_scene_types:
                raise ValueError(
                    f"scene '{scene.scene_id}' uses unsupported scene_type "
                    f"'{scene.scene_type}'"
                )
            if scene.psychological_stage not in valid_stage_ids:
                raise ValueError(
                    f"scene '{scene.scene_id}' uses unknown psychological_stage "
                    f"'{scene.psychological_stage}'"
                )
            if not (
                self.question_policy.questions_per_scene_min
                <= scene.question_count_target
                <= self.question_policy.questions_per_scene_max
            ):
                raise ValueError(
                    f"scene '{scene.scene_id}' question_count_target must be within "
                    "question_policy min/max bounds"
                )

            next_scene_ids = [
                value
                for value in (
                    scene.branch_outcomes.default_next_scene_id,
                    scene.branch_outcomes.if_match,
                    scene.branch_outcomes.if_difference,
                )
                if value is not None
            ]
            missing_targets = [
                scene_id for scene_id in next_scene_ids if scene_id not in valid_scene_ids
            ]
            if missing_targets:
                raise ValueError(
                    f"scene '{scene.scene_id}' references unknown next scene(s): "
                    + ", ".join(missing_targets)
                )

        return self
