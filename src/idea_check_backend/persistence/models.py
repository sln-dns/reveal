from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def generate_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SessionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ParticipantStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    COMPLETED = "completed"
    DROPPED = "dropped"


class RunStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    WAITING_FOR_ANSWERS = "waiting_for_answers"
    COMPLETED = "completed"
    FAILED = "failed"


class SceneStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class QuestionStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ANSWERED = "answered"
    EXPIRED = "expired"


class SummaryKind(StrEnum):
    SCENE = "scene"
    RUN = "run"


class Session(Base, TimestampMixin):
    __tablename__ = "session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    external_ref: Mapped[str | None] = mapped_column(String(100))
    scenario_key: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=SessionStatus.PENDING, nullable=False)
    lifecycle_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    participants: Mapped[list["SessionParticipant"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    scenario_runs: Mapped[list["ScenarioRun"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


class SessionParticipant(Base, TimestampMixin):
    __tablename__ = "session_participant"
    __table_args__ = (
        UniqueConstraint("session_id", "slot", name="uq_session_participant_slot"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False,
    )
    slot: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="participant")
    display_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        String(32),
        default=ParticipantStatus.INVITED,
        nullable=False,
    )
    state_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    generated_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[Session] = relationship(back_populates="participants")
    assigned_questions: Mapped[list["QuestionInstance"]] = relationship(
        back_populates="participant"
    )
    answers: Mapped[list["Answer"]] = relationship(back_populates="participant")


class ScenarioRun(Base, TimestampMixin):
    __tablename__ = "scenario_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False,
    )
    scenario_key: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_version: Mapped[str] = mapped_column(String(50), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.PENDING, nullable=False)
    runtime_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    generated_content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    current_scene_key: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    session: Mapped[Session] = relationship(back_populates="scenario_runs")
    scene_instances: Mapped[list["SceneInstance"]] = relationship(
        back_populates="scenario_run",
        cascade="all, delete-orphan",
        order_by="SceneInstance.position",
    )
    summaries: Mapped[list["Summary"]] = relationship(
        back_populates="scenario_run",
        cascade="all, delete-orphan",
    )


class SceneInstance(Base, TimestampMixin):
    __tablename__ = "scene_instance"
    __table_args__ = (
        UniqueConstraint("scenario_run_id", "position", name="uq_scene_instance_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_run_id: Mapped[str] = mapped_column(
        ForeignKey("scenario_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    scene_key: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=SceneStatus.PENDING, nullable=False)
    state_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    generated_content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scenario_run: Mapped[ScenarioRun] = relationship(back_populates="scene_instances")
    question_instances: Mapped[list["QuestionInstance"]] = relationship(
        back_populates="scene_instance",
        cascade="all, delete-orphan",
        order_by="QuestionInstance.position",
    )
    summaries: Mapped[list["Summary"]] = relationship(back_populates="scene_instance")


class QuestionInstance(Base, TimestampMixin):
    __tablename__ = "question_instance"
    __table_args__ = (
        UniqueConstraint("scene_instance_id", "position", name="uq_question_instance_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scene_instance_id: Mapped[str] = mapped_column(
        ForeignKey("scene_instance.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("session_participant.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_key: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=QuestionStatus.PENDING, nullable=False)
    state_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    prompt_text: Mapped[str | None] = mapped_column(Text)
    prompt_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    scene_instance: Mapped[SceneInstance] = relationship(back_populates="question_instances")
    participant: Mapped[SessionParticipant] = relationship(back_populates="assigned_questions")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="question_instance",
        cascade="all, delete-orphan",
    )


class Answer(Base, TimestampMixin):
    __tablename__ = "answer"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    question_instance_id: Mapped[str] = mapped_column(
        ForeignKey("question_instance.id", ondelete="CASCADE"),
        nullable=False,
    )
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("session_participant.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    question_instance: Mapped[QuestionInstance] = relationship(back_populates="answers")
    participant: Mapped[SessionParticipant] = relationship(back_populates="answers")


class Summary(Base, TimestampMixin):
    __tablename__ = "summary"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    scenario_run_id: Mapped[str] = mapped_column(
        ForeignKey("scenario_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    scene_instance_id: Mapped[str | None] = mapped_column(
        ForeignKey("scene_instance.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32), default=SummaryKind.SCENE, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    scenario_run: Mapped[ScenarioRun] = relationship(back_populates="summaries")
    scene_instance: Mapped[SceneInstance] = relationship(back_populates="summaries")
