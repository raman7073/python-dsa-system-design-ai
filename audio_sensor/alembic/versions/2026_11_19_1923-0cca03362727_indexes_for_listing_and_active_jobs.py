"""indexes for listing and active jobs

Revision ID: 0cca03362727
Revises: f167aa8f2327
Create Date: 2026-11-19 19:23:43.320989

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0cca03362727'
down_revision: str | Sequence[str] | None = 'f167aa8f2327'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # New indexes first, so user_id lookups are never without one. The
    # composite index starts with user_id, so it replaces ix_audio_user_id.
    op.create_index(
        "ix_audio_user_id_created_at", "audio", ["user_id", "created_at", "id"], unique=False
    )
    op.create_index(
        "ix_audio_active",
        "audio",
        ["user_id", "status"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.drop_index(op.f("ix_audio_user_id"), table_name="audio")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index(op.f("ix_audio_user_id"), "audio", ["user_id"], unique=False)
    op.drop_index(
        "ix_audio_active",
        table_name="audio",
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.drop_index("ix_audio_user_id_created_at", table_name="audio")
