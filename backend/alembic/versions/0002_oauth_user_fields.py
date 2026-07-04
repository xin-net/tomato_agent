"""add oauth user fields

Revision ID: 0002_oauth_user_fields
Revises: 0001_initial_schema
Create Date: 2026-07-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_oauth_user_fields"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "password_hash", nullable=True)
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    op.add_column(
        "users",
        sa.Column("auth_provider", sa.String(length=30), nullable=False, server_default="password"),
    )
    op.add_column("users", sa.Column("provider_subject", sa.String(length=255), nullable=True))
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_auth_provider", "users", ["auth_provider"], unique=False)
    op.create_index("ix_users_provider_subject", "users", ["provider_subject"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_provider_subject", table_name="users")
    op.drop_index("ix_users_auth_provider", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "provider_subject")
    op.drop_column("users", "auth_provider")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "email")
    op.alter_column("users", "password_hash", nullable=False)
