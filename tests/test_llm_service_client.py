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


def test_llm_service_prompt_explicitly_requires_russian() -> None:
    client = LLMServiceClient()

    prompt = client.build_prompt(_build_payload())

    assert "Отвечай только на русском языке." in prompt
    assert "Не смешивай русский и английский" in prompt
    assert "Все значения внутри JSON должны быть написаны по-русски." in prompt
    assert "Отдавай сильное предпочтение формату простого выбора из вариантов." in prompt
    assert "свой вариант" in prompt


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
                                        "intro_text": "Провайдер вернул русское вступление.",
                                        "questions": [
                                            "Какой формат вечера тебе сейчас ближе?",
                                            "Что помогает тебе быстро почувствовать лёгкость?",
                                        ],
                                        "transition_text": "Провайдер вернул русский переход.",
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
    assert result.generation.intro_text == "Провайдер вернул русское вступление."
    assert result.generation.questions == [
        "Какой формат вечера тебе сейчас ближе?",
        "Что помогает тебе быстро почувствовать лёгкость?",
    ]
    assert result.generation.transition_text == "Провайдер вернул русский переход."
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


def test_llm_service_falls_back_when_provider_returns_non_russian_content() -> None:
    client = LLMServiceClient(
        transport=lambda _prompt: json.dumps(
            {
                "intro_text": "Provider intro",
                "questions": ["Question one?", "Question two?"],
                "transition_text": "Provider transition",
            }
        )
    )

    result = client.generate_scene(_build_payload())

    assert result.generation.used_fallback is True
    assert result.log.used_fallback is True
    assert result.log.validation_error is not None
    assert "written in Russian" in result.log.validation_error


def _build_payload() -> SceneGenerationPayload:
    return SceneGenerationPayload(
        scene_id="scene_01_intro",
        scene_type="intro",
        scene_title="Старт маршрута",
        scene_purpose="Дать короткий контекст и запустить маршрут.",
        psychological_goal="Снизить напряжение и начать легко.",
        ladder_stages=["Разогрев", "Вкус"],
        allowed_question_families=["very_light_vibe"],
        forbidden_question_families=["self_analysis"],
        question_templates=[
            "Что тебе ближе для такого вечера: лёгкий флирт, спокойный уют, немного игры или свой вариант?",
            "С чего тебе легче начать: с шутки, с простого вопроса, с наблюдения вокруг или свой вариант?",
        ],
        question_count_target=2,
        transition_goal="Подвести игроков к более ясному направлению маршрута.",
        selected_world="evening_city",
        selected_tone="playful",
        product_goal="Помочь двум людям легко начать разговор.",
        experience_principles=["low_cognitive_load", "light_playful_tone"],
        max_answer_length_chars=180,
        default_answer_format="hybrid_choice_plus_text",
        allowed_answer_formats=["short_text", "single_choice", "hybrid_choice_plus_text"],
        preferred_question_style="fast_choice_with_optional_custom_text",
        preferred_option_count_min=3,
        preferred_option_count_max=4,
        allow_custom_answer_option=True,
        custom_answer_label="свой вариант",
        question_generation_rules=[
            "По умолчанию вопрос должен провоцировать быстрый выбор, а не длинное размышление.",
            "Предпочтительный формат: 3-4 коротких варианта прямо внутри вопроса плюс явная опция 'свой вариант'.",
        ],
    )
