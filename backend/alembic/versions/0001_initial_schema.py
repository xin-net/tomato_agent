"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200)),
        sa.Column("user_id", sa.String(length=100), index=True),
        sa.Column("crop", sa.String(length=50)),
        sa.Column("environment", sa.String(length=50)),
        sa.Column("growth_stage", sa.String(length=50)),
        sa.Column("symptoms", sa.Text()),
        sa.Column("affected_parts", sa.JSON()),
        sa.Column("severity", sa.String(length=50)),
        sa.Column("recent_weather", sa.String(length=100)),
        sa.Column("recent_fertilizer_use", sa.String(length=50)),
        sa.Column("recent_pesticide_use", sa.String(length=50)),
        sa.Column("days_to_harvest", sa.Integer()),
        sa.Column("suspected_problem", sa.String(length=100)),
        sa.Column("likelihood", sa.String(length=50)),
        sa.Column("status", sa.String(length=50), index=True),
        sa.Column("structured_data", sa.JSON()),
        sa.Column("current_plan", sa.JSON()),
        sa.Column("followup_date", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "case_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), index=True),
        sa.Column("event_type", sa.String(length=80), index=True),
        sa.Column("user_input", sa.Text()),
        sa.Column("system_output", sa.JSON()),
        sa.Column("structured_data", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "followups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), index=True),
        sa.Column("due_date", sa.Date(), index=True),
        sa.Column("checklist", sa.JSON()),
        sa.Column("status", sa.String(length=50), index=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("user_description", sa.Text()),
        sa.Column("result", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), index=True),
        sa.Column("followup_id", sa.Integer(), sa.ForeignKey("followups.id", ondelete="SET NULL"), index=True),
        sa.Column("due_at", sa.DateTime(timezone=True), index=True),
        sa.Column("channel", sa.String(length=50), index=True),
        sa.Column("status", sa.String(length=50), index=True),
        sa.Column("reason", sa.String(length=200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("reminders")
    op.drop_table("followups")
    op.drop_table("case_events")
    op.drop_table("cases")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
