"""
Revision ID: 0002_add_refresh_tokens
Revises: 0001_initial_auth
Create Date: 2026-02-18 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_add_refresh_tokens"
down_revision = "0001_initial_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users", sa.Column("encrypted_google_refresh_token", sa.Text(), nullable=True)
    )
    op.add_column("users", sa.Column("refresh_token", sa.String(), nullable=True))
    op.drop_column("users", "google_refresh_token")


def downgrade():
    op.add_column(
        "users", sa.Column("google_refresh_token", sa.String(), nullable=True)
    )
    op.drop_column("users", "refresh_token")
    op.drop_column("users", "encrypted_google_refresh_token")
