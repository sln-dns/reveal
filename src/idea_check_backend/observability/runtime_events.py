from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

RUNTIME_EVENT_LOGGER_NAME = "idea_check_backend.runtime_events"


class RuntimeEventName:
    SESSION_CREATED = "session_created"
    PARTICIPANT_JOINED = "participant_joined"
    SCENARIO_RUN_STARTED = "scenario_run_started"
    SCENE_GENERATION_REQUESTED = "scene_generation_requested"
    SCENE_GENERATION_COMPLETED = "scene_generation_completed"
    SCENE_ACTIVATED = "scene_activated"
    QUESTION_DELIVERED = "question_delivered"
    ANSWER_SUBMITTED = "answer_submitted"
    WAITING_FOR_SECOND_ANSWER = "waiting_for_second_answer"
    ANSWERS_REVEALED = "answers_revealed"
    SCENE_COMPLETED = "scene_completed"
    BRANCH_SELECTED = "branch_selected"
    RUN_COMPLETED = "run_completed"
    RUNTIME_ERROR = "runtime_error"


@dataclass(slots=True, frozen=True)
class RuntimeEvent:
    event_name: str
    timestamp: str
    session_id: str | None
    scenario_run_id: str | None
    scene_id: str | None
    participant_id: str | None
    participant_slot: int | None
    metadata: dict[str, Any]
    event_type: str = "runtime_event"

    def asdict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "event_name": self.event_name,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "scenario_run_id": self.scenario_run_id,
            "scene_id": self.scene_id,
            "participant_id": self.participant_id,
            "participant_slot": self.participant_slot,
            "metadata": self.metadata,
        }


class RuntimeEventLogger:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(RUNTIME_EVENT_LOGGER_NAME)

    def emit(
        self,
        event_name: str,
        *,
        session_id: str | None = None,
        scenario_run_id: str | None = None,
        scene_id: str | None = None,
        participant_id: str | None = None,
        participant_slot: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        level: int = logging.INFO,
    ) -> None:
        event = RuntimeEvent(
            event_name=event_name,
            timestamp=datetime.now(UTC).isoformat(),
            session_id=session_id,
            scenario_run_id=scenario_run_id,
            scene_id=scene_id,
            participant_id=participant_id,
            participant_slot=participant_slot,
            metadata=dict(metadata or {}),
        )
        self._logger.log(level, event_name, extra={"runtime_event": event.asdict()})

    def emit_error(
        self,
        *,
        error: Exception,
        session_id: str | None = None,
        scenario_run_id: str | None = None,
        scene_id: str | None = None,
        participant_id: str | None = None,
        participant_slot: int | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        payload = dict(metadata or {})
        payload.update(
            error_type=error.__class__.__name__,
            error_message=str(error),
        )
        self.emit(
            RuntimeEventName.RUNTIME_ERROR,
            session_id=session_id,
            scenario_run_id=scenario_run_id,
            scene_id=scene_id,
            participant_id=participant_id,
            participant_slot=participant_slot,
            metadata=payload,
            level=logging.ERROR,
        )


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        runtime_event = getattr(record, "runtime_event", None)
        if runtime_event is not None:
            payload = dict(runtime_event)
            payload.setdefault("level", record.levelname)
            payload.setdefault("logger", record.name)
            return json.dumps(payload, ensure_ascii=True, sort_keys=True)

        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def configure_logging(level: int = logging.INFO) -> None:
    root_logger = logging.getLogger()
    if root_logger.handlers:
        for handler in root_logger.handlers:
            handler.setFormatter(JsonLogFormatter())
        root_logger.setLevel(level)
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
