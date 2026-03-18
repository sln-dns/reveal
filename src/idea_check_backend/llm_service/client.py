from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from idea_check_backend.llm_service.prompt_builder import ScenePromptBuilder
from idea_check_backend.shared_types.scenario import (
    SceneGeneration,
    SceneGenerationLog,
    SceneGenerationPayload,
)
from idea_check_backend.shared_types.settings import Settings, get_settings


class _SceneGenerationResponse(BaseModel):
    intro_text: str
    questions: list[str] = Field(min_length=1, max_length=3)
    transition_text: str

    @field_validator("intro_text", "transition_text")
    @classmethod
    def _validate_text_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text fields must not be empty")
        if not _contains_cyrillic(cleaned):
            raise ValueError("text fields must be written in Russian")
        return cleaned

    @field_validator("questions")
    @classmethod
    def _validate_questions(cls, value: list[str]) -> list[str]:
        cleaned_questions = [question.strip() for question in value if question.strip()]
        if len(cleaned_questions) != len(value):
            raise ValueError("questions must not be empty")
        if any(not _contains_cyrillic(question) for question in cleaned_questions):
            raise ValueError("questions must be written in Russian")
        return cleaned_questions


@dataclass
class SceneGenerationResult:
    generation: SceneGeneration
    log: SceneGenerationLog


class LLMServiceClient:
    SUPPORTED_SCENE_IDS = {"scene_01_intro", "scene_02_direction"}

    def __init__(
        self,
        settings: Settings | None = None,
        prompt_builder: ScenePromptBuilder | None = None,
        transport: Callable[[str], str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._prompt_builder = prompt_builder or ScenePromptBuilder()
        self._transport = transport
        self._logger = logger or logging.getLogger(__name__)

    def supports_scene(self, scene_id: str) -> bool:
        return scene_id in self.SUPPORTED_SCENE_IDS

    @property
    def settings(self) -> Settings:
        return self._settings

    def build_prompt(self, payload: SceneGenerationPayload) -> str:
        return self._prompt_builder.build(payload)

    def build_fallback_generation(self, payload: SceneGenerationPayload) -> SceneGeneration:
        return self._build_fallback_generation(payload)

    def generate_scene(self, payload: SceneGenerationPayload) -> SceneGenerationResult:
        prompt = self.build_prompt(payload)
        raw_response = ""
        validation_error: str | None = None

        try:
            raw_response = self._generate_raw_response(prompt)
            parsed_response = self._parse_response(raw_response, payload.question_count_target)
            generation = SceneGeneration(
                scene_id=payload.scene_id,
                intro_text=parsed_response.intro_text,
                questions=parsed_response.questions,
                transition_text=parsed_response.transition_text,
                used_fallback=False,
            )
        except (ValidationError, ValueError, httpx.HTTPError) as exc:
            validation_error = str(exc)
            generation = self._build_fallback_generation(payload)
            if not raw_response:
                raw_response = "<fallback_without_model_response>"
            self._logger.warning(
                "scene_generation_fallback",
                extra={
                    "scene_id": payload.scene_id,
                    "provider": self._settings.llm_provider,
                    "provider_url": self._settings.ai_provider_url,
                    "model": self._settings.llm_model,
                    "error": validation_error,
                },
            )

        log_entry = SceneGenerationLog(
            scene_id=payload.scene_id,
            provider=self._settings.llm_provider,
            model=self._settings.llm_model,
            prompt=prompt,
            raw_response=raw_response,
            validation_error=validation_error,
            used_fallback=generation.used_fallback,
        )
        self._logger.info(
            "scene_generation_completed",
            extra={
                "scene_id": payload.scene_id,
                "provider": log_entry.provider,
                "provider_url": self._settings.ai_provider_url,
                "model": log_entry.model,
                "used_fallback": log_entry.used_fallback,
            },
        )
        return SceneGenerationResult(generation=generation, log=log_entry)

    def _generate_raw_response(self, prompt: str) -> str:
        if self._transport is not None:
            return self._transport(prompt)
        if self._settings.ai_provider_url:
            return self._call_provider(prompt)
        return self._build_stub_response(prompt)

    def _call_provider(self, prompt: str) -> str:
        if not self._settings.ai_provider_url:
            raise ValueError("AI_PROVIDER_URL is not configured")

        request_body = self._build_provider_request_body(prompt)
        headers = {"Content-Type": "application/json"}
        if self._settings.ai_provider_api_key:
            headers["Authorization"] = f"Bearer {self._settings.ai_provider_api_key}"

        self._logger.info(
            "llm_provider_request_started",
            extra={
                "provider": self._settings.llm_provider,
                "provider_url": self._settings.ai_provider_url,
                "model": self._settings.llm_model,
            },
        )

        try:
            with httpx.Client(
                timeout=self._settings.llm_timeout_seconds,
                trust_env=False,
            ) as client:
                response = client.post(
                    self._settings.ai_provider_url,
                    json=request_body,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ValueError("LLM provider request timed out") from exc
        except httpx.HTTPStatusError as exc:
            response_text = exc.response.text[:500].strip() or "<empty_response_body>"
            raise ValueError(
                f"LLM provider returned HTTP {exc.response.status_code}: {response_text}"
            ) from exc
        except httpx.RequestError as exc:
            raise ValueError(f"LLM provider request failed: {exc}") from exc

        try:
            response_payload = response.json()
        except json.JSONDecodeError as exc:
            raise ValueError("LLM provider returned non-JSON response") from exc

        return self._extract_provider_output(response_payload)

    def _build_provider_request_body(self, prompt: str) -> dict[str, object]:
        parsed_url = urlparse(self._settings.ai_provider_url or "")
        path = parsed_url.path.rstrip("/")

        if path.endswith("/chat/completions"):
            return {
                "model": self._settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
            }
        if path.endswith("/completions"):
            return {
                "model": self._settings.llm_model,
                "prompt": prompt,
            }
        return {
            "model": self._settings.llm_model,
            "input": prompt,
        }

    def _extract_provider_output(self, response_payload: object) -> str:
        if isinstance(response_payload, str):
            return response_payload
        if not isinstance(response_payload, dict):
            raise ValueError("LLM provider returned an unsupported JSON payload")

        direct_scene_payload = self._extract_scene_payload(response_payload)
        if direct_scene_payload is not None:
            return json.dumps(direct_scene_payload)

        for field_name in ("output_text", "text", "response", "generated_text"):
            field_value = response_payload.get(field_name)
            if isinstance(field_value, str) and field_value.strip():
                return field_value

        output_text = self._extract_text_from_output(response_payload.get("output"))
        if output_text is not None:
            return output_text

        choices = response_payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message_text = self._extract_text_from_choice(choice)
                if message_text is not None:
                    return message_text

        raise ValueError("LLM provider response did not include scene content")

    def _extract_scene_payload(self, payload: dict[str, object]) -> dict[str, object] | None:
        expected_keys = {"intro_text", "questions", "transition_text"}
        if expected_keys.issubset(payload.keys()):
            return payload

        for field_name in ("data", "result"):
            nested = payload.get(field_name)
            if isinstance(nested, dict) and expected_keys.issubset(nested.keys()):
                return nested

        return None

    def _extract_text_from_output(self, output: object) -> str | None:
        if not isinstance(output, list):
            return None
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        return None

    def _extract_text_from_choice(self, choice: dict[str, object]) -> str | None:
        message = choice.get("message")
        if not isinstance(message, dict):
            return None

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content
        if not isinstance(content, list):
            return None

        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text
        return None

    def _build_stub_response(self, prompt: str) -> str:
        if "scene_01_intro" in prompt:
            return json.dumps(
                {
                    "intro_text": (
                        "Вы только заходите в этот маршрут. "
                        "Поймайте лёгкое настроение и начните без напряжения."
                    ),
                    "questions": [
                        "Что тебе ближе для такого вечера: лёгкий флирт, спокойный уют, немного игры или свой вариант?",
                        "С чего тебе приятнее начать: с шутки, с простого вопроса, с наблюдения вокруг или со своего варианта?",
                    ],
                    "transition_text": (
                        "Отлично, общее направление уже чувствуется, "
                        "так что дальше можно стать чуть конкретнее."
                    ),
                }
            )
        return json.dumps(
            {
                "intro_text": (
                    "Маршрут начинает складываться. "
                    "Теперь можно точнее поймать его ритм и атмосферу."
                ),
                "questions": [
                    "Какое начало здесь тебе ближе: прогулка, бар, что-то спонтанное или свой вариант?",
                    "Что быстрее делает место твоим: музыка, разговор, движение или свой вариант?",
                    "Куда тебя скорее тянет: ближе к людям, в более тихий угол, к смене локации или в свой вариант?",
                ],
                "transition_text": (
                    "Хорошо, здесь уже достаточно сигнала, "
                    "чтобы перейти к темпу и ощущению контакта."
                ),
            }
        )

    def _parse_response(
        self,
        raw_response: str,
        question_count_target: int,
    ) -> _SceneGenerationResponse:
        parsed_json = self._load_json_payload(raw_response)
        parsed_response = _SceneGenerationResponse.model_validate(parsed_json)
        if len(parsed_response.questions) > min(3, question_count_target):
            raise ValueError("model returned too many questions")
        return parsed_response

    def _load_json_payload(self, raw_response: str) -> object:
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError:
            stripped_response = raw_response.strip()
            if stripped_response.startswith("```") and stripped_response.endswith("```"):
                stripped_response = "\n".join(stripped_response.splitlines()[1:-1]).strip()
            if stripped_response.startswith("json"):
                stripped_response = stripped_response[4:].strip()
            start = stripped_response.find("{")
            end = stripped_response.rfind("}")
            if start == -1 or end == -1 or start >= end:
                raise
            return json.loads(stripped_response[start : end + 1])

    def _build_fallback_generation(self, payload: SceneGenerationPayload) -> SceneGeneration:
        question_count = min(
            3,
            payload.question_count_target,
            max(1, len(payload.question_templates)),
        )
        questions = payload.question_templates[:question_count]
        intro_title = payload.scene_title or payload.scene_type.replace("_", " ").title()
        intro_text = (
            f"{intro_title}. {payload.scene_purpose} "
            f"Тон сцены: {payload.selected_tone}. Мир: {payload.selected_world}."
        )
        transition_text = payload.transition_goal
        return SceneGeneration(
            scene_id=payload.scene_id,
            intro_text=intro_text,
            questions=questions,
            transition_text=transition_text,
            used_fallback=True,
        )


_CYRILLIC_PATTERN = re.compile(r"[А-Яа-яЁё]")


def _contains_cyrillic(value: str) -> bool:
    return bool(_CYRILLIC_PATTERN.search(value))
