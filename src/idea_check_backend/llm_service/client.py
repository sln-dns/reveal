from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable
from urllib import error, request

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
        return cleaned

    @field_validator("questions")
    @classmethod
    def _validate_questions(cls, value: list[str]) -> list[str]:
        cleaned_questions = [question.strip() for question in value if question.strip()]
        if len(cleaned_questions) != len(value):
            raise ValueError("questions must not be empty")
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

    def build_prompt(self, payload: SceneGenerationPayload) -> str:
        return self._prompt_builder.build(payload)

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
        except (ValidationError, ValueError, error.URLError, TimeoutError) as exc:
            validation_error = str(exc)
            generation = self._build_fallback_generation(payload)
            if not raw_response:
                raw_response = "<fallback_without_model_response>"
            self._logger.warning(
                "scene_generation_fallback",
                extra={
                    "scene_id": payload.scene_id,
                    "provider": self._settings.llm_provider,
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
                "model": log_entry.model,
                "used_fallback": log_entry.used_fallback,
            },
        )
        return SceneGenerationResult(generation=generation, log=log_entry)

    def _generate_raw_response(self, prompt: str) -> str:
        if self._transport is not None:
            return self._transport(prompt)
        if self._settings.llm_provider == "openai" and self._settings.openai_api_key:
            return self._call_openai(prompt)
        return self._build_stub_response(prompt)

    def _call_openai(self, prompt: str) -> str:
        request_body = json.dumps(
            {
                "model": self._settings.llm_model,
                "input": prompt,
            }
        ).encode("utf-8")
        http_request = request.Request(
            self._settings.openai_base_url,
            data=request_body,
            headers={
                "Authorization": f"Bearer {self._settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with request.urlopen(
            http_request,
            timeout=self._settings.llm_timeout_seconds,
        ) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        return self._extract_openai_output_text(response_payload)

    def _extract_openai_output_text(self, response_payload: dict) -> str:
        output = response_payload.get("output", [])
        for item in output:
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return text
        raise ValueError("OpenAI response did not include text output")

    def _build_stub_response(self, prompt: str) -> str:
        if "scene_01_intro" in prompt:
            return json.dumps(
                {
                    "intro_text": (
                        "You are at the start of the route. "
                        "Pick an easy vibe and enter the scene lightly."
                    ),
                    "questions": [
                        "What kind of evening mood feels easiest for you right now?",
                        "What helps you enter a new conversation without tension?",
                    ],
                    "transition_text": (
                        "Nice. The route has a direction now, "
                        "so the next choice can get a bit more specific."
                    ),
                }
            )
        return json.dumps(
            {
                "intro_text": (
                    "The route starts taking shape. "
                    "Now the mood needs a clearer direction."
                ),
                "questions": [
                    "Which beginning feels most natural for this kind of route?",
                    "What atmosphere quickly makes a place feel like yours?",
                    "Where does your attention go first in a scene like this?",
                ],
                "transition_text": (
                    "Good. There is enough signal here "
                    "to move toward pace and chemistry."
                ),
            }
        )

    def _parse_response(
        self,
        raw_response: str,
        question_count_target: int,
    ) -> _SceneGenerationResponse:
        parsed_json = json.loads(raw_response)
        parsed_response = _SceneGenerationResponse.model_validate(parsed_json)
        if len(parsed_response.questions) > min(3, question_count_target):
            raise ValueError("model returned too many questions")
        return parsed_response

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
            f"Tone: {payload.selected_tone}. World: {payload.selected_world}."
        )
        transition_text = payload.transition_goal
        return SceneGeneration(
            scene_id=payload.scene_id,
            intro_text=intro_text,
            questions=questions,
            transition_text=transition_text,
            used_fallback=True,
        )
