"""job recovery fields

Revision ID: 9ed818828192
Revises: d5a9aa8bb6e3
Create Date: 2026-11-19 17:47:00.347478

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes  # autogenerate emits sqlmodel.sql.sqltypes.AutoString for str columns

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9ed818828192"
down_revision: str | Sequence[str] | None = "d5a9aa8bb6e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Existing rows get server defaults (the original job options, and one
    # attempt for jobs that already ran); the defaults are then dropped so
    # new rows take their values from the model.
    defaults = {"padding_ms": "150", "beep": sa.false(), "attempts": "1"}
    op.add_column(
        "audio",
        sa.Column(
            "padding_ms",
            sa.Integer(),
            nullable=False,
            server_default=defaults["padding_ms"],
        ),
    )
    op.add_column(
        "audio",
        sa.Column(
            "beep", sa.Boolean(), nullable=False, server_default=defaults["beep"]
        ),
    )
    op.add_column(
        "audio",
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=defaults["attempts"],
        ),
    )
    for column in defaults:
        op.alter_column("audio", column, server_default=None)
    op.add_column(
        "audio",
        sa.Column(
            "task_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
    )
    op.add_column(
        "audio",
        sa.Column("queued_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
    )
    op.add_column(
        "audio",
        sa.Column("started_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("audio", "started_at")
    op.drop_column("audio", "queued_at")
    op.drop_column("audio", "task_id")
    op.drop_column("audio", "attempts")
    op.drop_column("audio", "beep")
    op.drop_column("audio", "padding_ms")
