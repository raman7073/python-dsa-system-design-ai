"""storage keys instead of absolute paths

Revision ID: f167aa8f2327
Revises: 9ed818828192
Create Date: 2026-11-19 18:15:03.906948

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f167aa8f2327"
down_revision: str | Sequence[str] | None = "9ed818828192"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Rows from before paths were stored relative hold absolute local paths
# (e.g. C:\...\storage\uploads\<id>.mp3). Storage is addressed by key now
# ("uploads/<id>.mp3"), which also works for S3 and inside containers.
# file_path is always under uploads/, censored_file_path under censored/.
# Regexes are bound parameters, so their backslashes need no SQL escaping.
_ABSOLUTE = r"^([A-Za-z]:|/|\\)"  # C:..., /..., or \\server\...
_UP_TO_LAST_SEPARATOR = r"^.*[\\/]"  # everything before the file name


def upgrade() -> None:
    """Upgrade schema."""
    for column, prefix in (
        ("file_path", "uploads"),
        ("censored_file_path", "censored"),
    ):
        op.execute(
            sa.text(
                f"UPDATE audio SET {column} = :prefix || '/' || "
                f"regexp_replace({column}, :up_to_name, '') "
                f"WHERE {column} ~ :absolute"
            ).bindparams(
                prefix=prefix, up_to_name=_UP_TO_LAST_SEPARATOR, absolute=_ABSOLUTE
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    # The old absolute paths can't be restored, and the keys work either way.
