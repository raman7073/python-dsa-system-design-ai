"""censor options and sound effects

Revision ID: 5ac032113fa0
Revises: 0cca03362727
Create Date: 2026-11-19 21:25:01.815814

"""
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes  # autogenerate emits sqlmodel.sql.sqltypes.AutoString for str columns
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5ac032113fa0'
down_revision: str | Sequence[str] | None = '0cca03362727'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


FK_AUDIO_SOUND_EFFECT = "fk_audio_sound_effect_id_sound_effects"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "sound_effects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("file_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_sound_effects_user_id_name",
        "sound_effects",
        ["user_id", "name"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "audio_transcripts",
        sa.Column("audio_id", sa.Uuid(), nullable=False),
        sa.Column("words", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["audio_id"], ["audio.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("audio_id"),
    )

    op.add_column(
        "audio", sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True)
    )
    # The columns below can't be NULL, and the table already has rows: each
    # is added with a server default that fills them in.

    # censor_mode replaces beep: carry each job's setting over, then drop beep.
    op.add_column(
        "audio",
        sa.Column("censor_mode", sa.String(length=20), nullable=False, server_default="mute"),
    )
    op.execute("UPDATE audio SET censor_mode = 'beep' WHERE beep")
    op.alter_column("audio", "censor_mode", server_default=None)
    op.drop_column("audio", "beep")

    # An empty list means "no custom words"; the default stays, matching the model.
    op.add_column(
        "audio",
        sa.Column(
            "custom_words", postgresql.ARRAY(sa.TEXT()), server_default="{}", nullable=False
        ),
    )

    # Existing rows: last changed when they finished (or were created).
    op.add_column(
        "audio",
        sa.Column(
            "updated_at",
            sqlmodel.sql.sqltypes.UTCDateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute("UPDATE audio SET updated_at = COALESCE(finished_at, created_at)")
    op.alter_column("audio", "updated_at", server_default=None)

    op.add_column("audio", sa.Column("sound_effect_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        FK_AUDIO_SOUND_EFFECT,
        "audio",
        "sound_effects",
        ["sound_effect_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_audio_sound_effect_id",
        "audio",
        ["sound_effect_id"],
        unique=False,
        postgresql_where=sa.text("sound_effect_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_audio_sound_effect_id",
        table_name="audio",
        postgresql_where=sa.text("sound_effect_id IS NOT NULL"),
    )
    op.drop_constraint(FK_AUDIO_SOUND_EFFECT, "audio", type_="foreignkey")
    op.drop_column("audio", "sound_effect_id")
    op.drop_column("audio", "updated_at")
    op.drop_column("audio", "custom_words")

    # Back to the boolean: only "beep" maps to true (a sound effect becomes mute).
    op.add_column(
        "audio", sa.Column("beep", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.execute("UPDATE audio SET beep = (censor_mode = 'beep')")
    op.alter_column("audio", "beep", server_default=None)
    op.drop_column("audio", "censor_mode")

    op.drop_column("audio", "name")
    op.drop_table("audio_transcripts")
    op.drop_index(
        "uq_sound_effects_user_id_name",
        table_name="sound_effects",
        postgresql_nulls_not_distinct=True,
    )
    op.drop_table("sound_effects")
