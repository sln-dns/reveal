from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260316_000001"
down_revision = None
branch_labels = None
depends_on = None


def timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "session",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_ref", sa.String(length=100), nullable=True),
        sa.Column("scenario_key", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("lifecycle_state", sa.JSON(), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "session_participant",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("state_payload", sa.JSON(), nullable=False),
        sa.Column("generated_profile", sa.JSON(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "slot", name="uq_session_participant_slot"),
    )
    op.create_table(
        "scenario_run",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("scenario_key", sa.String(length=100), nullable=False),
        sa.Column("scenario_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("runtime_state", sa.JSON(), nullable=False),
        sa.Column("generated_content", sa.JSON(), nullable=False),
        sa.Column("current_scene_key", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["session_id"], ["session.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "scene_instance",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scenario_run_id", sa.String(length=36), nullable=False),
        sa.Column("scene_key", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("state_payload", sa.JSON(), nullable=False),
        sa.Column("generated_content", sa.JSON(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["scenario_run_id"], ["scenario_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scenario_run_id", "position", name="uq_scene_instance_position"),
    )
    op.create_table(
        "question_instance",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scene_instance_id", sa.String(length=36), nullable=False),
        sa.Column("participant_id", sa.String(length=36), nullable=False),
        sa.Column("question_key", sa.String(length=100), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("state_payload", sa.JSON(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("prompt_payload", sa.JSON(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["participant_id"], ["session_participant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scene_instance_id"], ["scene_instance.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_instance_id", "position", name="uq_question_instance_position"),
    )
    op.create_table(
        "answer",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("question_instance_id", sa.String(length=36), nullable=False),
        sa.Column("participant_id", sa.String(length=36), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_payload", sa.JSON(), nullable=False),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["participant_id"], ["session_participant.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["question_instance_id"],
            ["question_instance.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "summary",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("scenario_run_id", sa.String(length=36), nullable=False),
        sa.Column("scene_instance_id", sa.String(length=36), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_payload", sa.JSON(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        timestamp_column("created_at"),
        timestamp_column("updated_at"),
        sa.ForeignKeyConstraint(["scenario_run_id"], ["scenario_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scene_instance_id"], ["scene_instance.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("summary")
    op.drop_table("answer")
    op.drop_table("question_instance")
    op.drop_table("scene_instance")
    op.drop_table("scenario_run")
    op.drop_table("session_participant")
    op.drop_table("session")
