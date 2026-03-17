from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class PairFlowStateKind(StrEnum):
    WAITING = "waiting"
    ANSWERING = "answering"
    REVEAL = "reveal"
    COMPLETED = "completed"


class SubmitAnswerOutcome(StrEnum):
    WAITING = "waiting"
    REVEAL = "reveal"
    PROGRESSED = "progressed"
    COMPLETED = "completed"


class ParticipantIdentity(BaseModel):
    id: str
    slot: int
    display_name: str | None
    status: str


class SessionSummary(BaseModel):
    id: str
    scenario_key: str
    status: str
    has_started_run: bool
    active: bool


class RunSummary(BaseModel):
    id: str
    status: str
    phase: str
    scene_position: int | None
    total_scenes: int | None
    current_scene_key: str | None


class QuestionStateResponse(BaseModel):
    id: str
    participant_id: str
    participant_slot: int
    question_key: str
    prompt_text: str | None
    status: str
    answered: bool
    answer_text: str | None


class SceneStateResponse(BaseModel):
    id: str
    key: str
    title: str | None
    purpose: str | None
    intro_text: str | None
    transition_text: str | None
    used_fallback: bool
    position: int
    status: str
    phase: str
    revealed: bool
    questions: list[QuestionStateResponse]


class PairFlowStateResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    session: SessionSummary
    participant: ParticipantIdentity
    run: RunSummary | None
    state_kind: PairFlowStateKind
    waiting_for_partner: bool
    can_reveal: bool
    completed: bool
    current_scene: SceneStateResponse | None
    answered_current_question: bool
    updated_at: datetime


class CreateSessionRequest(BaseModel):
    display_name: str | None = None


class JoinSessionRequest(BaseModel):
    display_name: str | None = None


class SubmitAnswerRequest(BaseModel):
    content_text: str
    content_payload: dict[str, object] | None = None


class CreateSessionResponse(BaseModel):
    access: ParticipantIdentity
    state: PairFlowStateResponse


class JoinSessionResponse(BaseModel):
    access: ParticipantIdentity
    state: PairFlowStateResponse


class SubmitAnswerResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    outcome: SubmitAnswerOutcome
    state: PairFlowStateResponse
    reveal: SceneStateResponse | None
    advanced_to_next_scene: bool
    run_completed: bool
