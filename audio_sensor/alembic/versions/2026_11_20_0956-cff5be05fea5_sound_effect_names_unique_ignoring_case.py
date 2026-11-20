"""sound effect names unique ignoring case

Revision ID: cff5be05fea5
Revises: b2276240746b
Create Date: 2026-11-20 09:56:06.778071

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cff5be05fea5"
down_revision: str | Sequence[str] | None = "b2276240746b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Fails if a user already has names differing only in case; rename or
    # delete those first.
    op.create_index(
        "uq_sound_effects_user_id_lower_name",
        "sound_effects",
        ["user_id", sa.text("lower(name)")],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.drop_index("uq_sound_effects_user_id_name", table_name="sound_effects")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index(
        "uq_sound_effects_user_id_name",
        "sound_effects",
        ["user_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.drop_index("uq_sound_effects_user_id_lower_name", table_name="sound_effects")
