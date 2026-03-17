from __future__ import annotations

import json
from pathlib import Path

import pytest

from idea_check_backend.shared_types.settings import Settings
from idea_check_backend.smoke.generate_scene import SmokeGenerationError, run_smoke_generation


def test_run_smoke_generation_writes_artifacts(tmp_path: Path) -> None:
    artifact_dir = run_smoke_generation(
        output_root=tmp_path,
        settings=Settings(
            ai_model="test-model",
            ai_provider_api_key="test-secret",
            ai_provider_url="https://provider.example/v1/responses",
        ),
        transport=lambda _prompt: json.dumps(
            {
                "intro_text": "Provider intro",
                "questions": ["Question one?", "Question two?"],
                "transition_text": "Provider transition",
            }
        ),
    )

    result_json = artifact_dir / "result.json"
    result_md = artifact_dir / "result.md"

    assert result_json.exists()
    assert result_md.exists()
    saved_payload = json.loads(result_json.read_text(encoding="utf-8"))
    assert saved_payload["generation"]["used_fallback"] is False
    assert saved_payload["scene_id"] == "scene_01_intro"
    assert "Provider intro" in result_md.read_text(encoding="utf-8")


def test_run_smoke_generation_rejects_fallback(tmp_path: Path) -> None:
    with pytest.raises(SmokeGenerationError, match="without fallback"):
        run_smoke_generation(
            output_root=tmp_path,
            settings=Settings(
                ai_model="test-model",
                ai_provider_api_key="test-secret",
                ai_provider_url="https://provider.example/v1/responses",
            ),
            transport=lambda _prompt: "not-json",
        )


def test_run_smoke_generation_requires_provider_env() -> None:
    # Smoke tests must stay deterministic even if a developer has real AI_* env vars locally.
    with pytest.raises(SmokeGenerationError, match="AI_PROVIDER_API_KEY, AI_PROVIDER_URL"):
        run_smoke_generation(
            settings=Settings(ai_model="test-model"),
            transport=lambda _prompt: "{}",
        )
