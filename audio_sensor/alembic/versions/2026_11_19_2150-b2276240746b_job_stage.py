"""job stage

Revision ID: b2276240746b
Revises: 5ac032113fa0
Create Date: 2026-11-19 21:50:33.793729

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2276240746b'
down_revision: str | Sequence[str] | None = '5ac032113fa0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("audio", sa.Column("stage", sa.String(length=20), nullable=True))
    # Jobs that already completed went through every step. (They have no
    # stored transcript, though: they ran before transcripts were kept.)
    op.execute("UPDATE audio SET stage = 'rendered' WHERE status = 'completed'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("audio", "stage")
