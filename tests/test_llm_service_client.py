from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from idea_check_backend.llm_service.client import LLMServiceClient
from idea_check_backend.shared_types.scenario import SceneGenerationPayload
from idea_check_backend.shared_types.settings import Settings


def test_settings_load_ai_provider_fields(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "AI_MODEL=test-model",
                "AI_PROVIDER_API_KEY=test-secret",
                "AI_PROVIDER_URL=https://provider.example/v1/responses",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.ai_model == "test-model"
    assert settings.ai_provider_api_key == "test-secret"
    assert settings.ai_provider_url == "https://provider.example/v1/responses"
    assert settings.llm_model == "test-model"
    assert settings.llm_provider == "provider.example"


def test_llm_service_calls_provider_with_responses_api_payload() -> None:
    requests: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers["Content-Length"])
            body = self.rfile.read(content_length).decode("utf-8")
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "payload": json.loads(body),
                }
            )

            response_payload = {
                "output": [
                    {
                        "content": [
                            {
                                "text": json.dumps(
                                    {
                                        "intro_text": "Provider intro",
                                        "questions": [
                                            "Question one?",
                                            "Question two?",
                                        ],
                                        "transition_text": "Provider transition",
                                    }
                                )
                            }
                        ]
                    }
                ]
            }
            encoded_response = json.dumps(response_payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded_response)))
            self.end_headers()
            self.wfile.write(encoded_response)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        client = LLMServiceClient(
            settings=Settings(
                ai_model="test-model",
                ai_provider_api_key="test-secret",
                ai_provider_url=f"http://127.0.0.1:{server.server_port}/v1/responses",
                llm_timeout_seconds=1.0,
            )
        )

        result = client.generate_scene(_build_payload())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert result.generation.used_fallback is False
    assert result.generation.intro_text == "Provider intro"
    assert result.generation.questions == ["Question one?", "Question two?"]
    assert result.generation.transition_text == "Provider transition"
    assert requests == [
        {
            "path": "/v1/responses",
            "authorization": "Bearer test-secret",
            "payload": {
                "model": "test-model",
                "input": result.log.prompt,
            },
        }
    ]


def test_llm_service_falls_back_on_provider_timeout() -> None:
    client = LLMServiceClient(
        settings=Settings(
            ai_model="test-model",
            ai_provider_api_key="test-secret",
            ai_provider_url="http://127.0.0.1:1/v1/responses",
            llm_timeout_seconds=0.01,
        )
    )

    result = client.generate_scene(_build_payload())

    assert result.generation.used_fallback is True
    assert result.log.used_fallback is True
    assert result.log.validation_error is not None


def _build_payload() -> SceneGenerationPayload:
    return SceneGenerationPayload(
        scene_id="scene_01_intro",
        scene_type="intro",
        scene_title="Start of Route",
        scene_purpose="Give a short context and start the route.",
        psychological_goal="Lower tension and begin lightly.",
        ladder_stages=["Warm-up", "Taste"],
        allowed_question_families=["very_light_vibe"],
        forbidden_question_families=["self_analysis"],
        question_templates=[
            "What kind of evening mood feels easiest for you right now?",
            "What helps you enter a new conversation without tension?",
        ],
        question_count_target=2,
        transition_goal="Move the players toward a clearer route direction.",
        selected_world="evening_city",
        selected_tone="playful",
        product_goal="Help two people start talking easily.",
        experience_principles=["low_cognitive_load", "light_playful_tone"],
        max_answer_length_chars=180,
    )
