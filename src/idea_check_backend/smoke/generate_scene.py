from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from idea_check_backend.llm_service.client import LLMServiceClient
from idea_check_backend.scenario_engine.blueprint_loader import (
    REPOSITORY_ROOT,
    ScenarioBlueprintRepository,
)
from idea_check_backend.shared_types.scenario import SceneGenerationPayload
from idea_check_backend.shared_types.scenario_blueprint import ScenarioBlueprint, SceneDefinition
from idea_check_backend.shared_types.settings import Settings, get_settings

DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts" / "smoke_generation"


class SmokeGenerationError(RuntimeError):
    """Raised when the manual smoke flow cannot complete successfully."""


@dataclass
class SmokeGenerationArtifact:
    generated_at: str
    scenario_key: str
    scene_id: str
    provider_url: str
    model: str
    artifact_dir: str
    payload: dict[str, object]
    generation: dict[str, object]
    log: dict[str, object]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a manual smoke generation against the configured AI provider."
    )
    parser.add_argument(
        "--scenario",
        default="date_route",
        help="Scenario blueprint key. Defaults to date_route.",
    )
    parser.add_argument(
        "--scene-id",
        default=None,
        help="Optional supported scene id. Defaults to the first supported scene in the blueprint.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_ROOT),
        help=f"Directory where smoke artifacts are written. Defaults to {DEFAULT_OUTPUT_ROOT}.",
    )
    args = parser.parse_args()

    try:
        artifact_dir = run_smoke_generation(
            scenario_key=args.scenario,
            requested_scene_id=args.scene_id,
            output_root=Path(args.output_dir),
        )
    except SmokeGenerationError as exc:
        print(f"Smoke generation failed: {exc}", file=sys.stderr)
        return 1

    print(f"Smoke generation succeeded. Artifacts saved to {artifact_dir}")
    return 0


def run_smoke_generation(
    scenario_key: str = "date_route",
    requested_scene_id: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    settings: Settings | None = None,
    transport: Callable[[str], str] | None = None,
) -> Path:
    loaded_settings = settings or get_settings()
    _validate_settings(loaded_settings)

    blueprint = ScenarioBlueprintRepository().get(scenario_key)
    client = LLMServiceClient(settings=loaded_settings, transport=transport)
    scene = _select_scene(blueprint, client, requested_scene_id)
    payload = _build_payload(blueprint, scene)
    result = client.generate_scene(payload)

    if result.generation.used_fallback:
        details = result.log.validation_error or "provider response was replaced by fallback"
        raise SmokeGenerationError(
            "real provider call did not produce a valid scene JSON without fallback: "
            f"{details}"
        )

    generated_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = output_root / f"{scenario_key}_{scene.scene_id}_{generated_at}"
    artifact_dir.mkdir(parents=True, exist_ok=False)

    artifact = SmokeGenerationArtifact(
        generated_at=generated_at,
        scenario_key=scenario_key,
        scene_id=scene.scene_id,
        provider_url=loaded_settings.ai_provider_url or "",
        model=loaded_settings.ai_model,
        artifact_dir=str(artifact_dir),
        payload=payload.model_dump(mode="json"),
        generation=result.generation.model_dump(mode="json"),
        log=result.log.model_dump(mode="json"),
    )
    _write_artifacts(artifact_dir, artifact)
    return artifact_dir


def _validate_settings(settings: Settings) -> None:
    missing_vars = [
        env_name
        for env_name, value in (
            ("AI_MODEL", settings.ai_model.strip()),
            ("AI_PROVIDER_API_KEY", (settings.ai_provider_api_key or "").strip()),
            ("AI_PROVIDER_URL", (settings.ai_provider_url or "").strip()),
        )
        if not value
    ]
    if missing_vars:
        raise SmokeGenerationError(
            "missing required AI configuration: "
            + ", ".join(missing_vars)
            + ". Populate them in .env or your shell before running the smoke flow."
        )


def _select_scene(
    blueprint: ScenarioBlueprint,
    client: LLMServiceClient,
    requested_scene_id: str | None,
) -> SceneDefinition:
    supported_scenes = [
        scene for scene in blueprint.scene_flow if client.supports_scene(scene.scene_id)
    ]
    if not supported_scenes:
        raise SmokeGenerationError(
            "scenario "
            f"'{blueprint.scenario_id}' does not contain a scene supported by "
            "the current LLM client"
        )

    if requested_scene_id is None:
        return supported_scenes[0]

    for scene in supported_scenes:
        if scene.scene_id == requested_scene_id:
            return scene

    supported_ids = ", ".join(scene.scene_id for scene in supported_scenes)
    raise SmokeGenerationError(
        f"scene '{requested_scene_id}' is not supported for smoke generation. "
        f"Supported scenes: {supported_ids}"
    )


def _build_payload(blueprint: ScenarioBlueprint, scene: SceneDefinition) -> SceneGenerationPayload:
    return SceneGenerationPayload(
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


def _write_artifacts(artifact_dir: Path, artifact: SmokeGenerationArtifact) -> None:
    json_path = artifact_dir / "result.json"
    markdown_path = artifact_dir / "result.md"

    json_path.write_text(
        json.dumps(asdict(artifact), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")


def _render_markdown(artifact: SmokeGenerationArtifact) -> str:
    generation = artifact.generation
    questions = generation["questions"]
    questions_block = "\n".join(f"- {question}" for question in questions)
    prompt = artifact.log["prompt"].strip()
    raw_response = artifact.log["raw_response"].strip()
    return (
        f"# Smoke Generation Result\n\n"
        f"- Generated at: `{artifact.generated_at}`\n"
        f"- Scenario: `{artifact.scenario_key}`\n"
        f"- Scene ID: `{artifact.scene_id}`\n"
        f"- Model: `{artifact.model}`\n"
        f"- Provider URL: `{artifact.provider_url}`\n"
        f"- Artifact directory: `{artifact.artifact_dir}`\n\n"
        f"## Scene Output\n\n"
        f"**Intro**\n\n{generation['intro_text']}\n\n"
        f"**Questions**\n\n{questions_block}\n\n"
        f"**Transition**\n\n{generation['transition_text']}\n\n"
        f"## Prompt\n\n```text\n{prompt}\n```\n\n"
        f"## Raw Response\n\n```text\n{raw_response}\n```\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
