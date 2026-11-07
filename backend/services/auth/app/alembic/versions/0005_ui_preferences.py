"""Persist interface language and colour theme for existing and new users.

Revision ID: 0005_ui_preferences
Revises: 0004_add_user_settings_table
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_ui_preferences"
down_revision = "0004_add_user_settings_table"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_settings",
        sa.Column("ui_language", sa.String(2), nullable=False, server_default="en"),
    )
    op.add_column(
        "user_settings",
        sa.Column("theme", sa.String(5), nullable=False, server_default="dark"),
    )


def downgrade():
    op.drop_column("user_settings", "theme")
    op.drop_column("user_settings", "ui_language")
