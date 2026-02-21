"""
Revision ID: 0001_initial_auth
Revises:
Create Date: 2026-02-17 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_auth"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("picture_url", sa.String(), nullable=True),
        sa.Column("auth_provider", sa.String(), nullable=False, server_default="local"),
        sa.Column("google_id", sa.String(), nullable=True, unique=True),
        sa.Column("google_refresh_token", sa.String(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
