"""Sound effects: short clips that can replace censored words
(censor_mode sound_effect). Users upload their own; built-in ones (no owner)
are available to everyone."""

import asyncio
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import get_api_settings
from app.database.models import AudioFile, AudioStatus, SoundEffect, User
from app.storage import (
    SOUND_EFFECT_SUFFIXES,
    Download,
    Storage,
    get_storage,
    media_type_for,
    sound_effect_key,
)

MAX_NAME_LENGTH = 100


class SoundEffectNotFoundError(LookupError):
    """No sound effect with that ID that this user may use (or, for delete,
    owns: built-in effects can't be deleted)."""


class InvalidSoundEffectError(ValueError):
    """A bad name or file type."""


class SoundEffectNameTakenError(ValueError):
    """The user already has a sound effect with this name."""


class TooManySoundEffectsError(RuntimeError):
    def __init__(self, limit: int):
        self.limit = limit
        super().__init__(f"You already have {limit} sound effects; delete one first")


class SoundEffectInUseError(RuntimeError):
    """Jobs still waiting to be rendered use this effect."""


@dataclass
class StoredSoundEffect:
    download: Download
    media_type: str
    download_filename: str


class SoundEffectService:
    """Knows nothing about HTTP. Storage calls block, so they run in a thread."""

    def __init__(
        self,
        session: AsyncSession,
        storage: Storage | None = None,
        max_bytes: int | None = None,
        max_per_user: int | None = None,
    ):
        self.session = session
        self.storage = storage or get_storage()
        self.max_bytes = max_bytes or get_api_settings().max_sound_effect_bytes
        self.max_per_user = max_per_user or get_api_settings().MAX_SOUND_EFFECTS_PER_USER

    async def create(
        self, owner_id: UUID, name: str, filename: str | None, data: BinaryIO
    ) -> SoundEffect:
        """Store an uploaded effect for `owner_id`.

        Raises InvalidSoundEffectError (bad name or file type),
        SoundEffectNameTakenError, TooManySoundEffectsError and
        UploadTooLargeError (over MAX_SOUND_EFFECT_MB). Nothing is kept
        unless both the file and the row are stored.
        """
        name = name.strip()
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise InvalidSoundEffectError(f"name must be 1-{MAX_NAME_LENGTH} characters")
        suffix = PurePosixPath(filename or "").suffix.lower()
        if suffix not in SOUND_EFFECT_SUFFIXES:
            raise InvalidSoundEffectError(
                f"Sound effects must be one of: {', '.join(SOUND_EFFECT_SUFFIXES)}"
            )

        # As with audio uploads: quick checks first, then no connection or
        # lock is held while the file is stored.
        await self._check_room(owner_id, name)
        await self.session.commit()
        effect_id = uuid4()
        key = sound_effect_key(effect_id, suffix)
        await asyncio.to_thread(self.storage.save, key, data, self.max_bytes)

        try:
            # The authoritative checks, with the insert, under the user's lock.
            await self.session.exec(select(User).where(User.id == owner_id).with_for_update())
            await self._check_room(owner_id, name)
            effect = SoundEffect(id=effect_id, user_id=owner_id, name=name, file_path=key)
            self.session.add(effect)
            try:
                await self.session.commit()
            except IntegrityError as exc:  # the unique (user_id, name) index
                raise SoundEffectNameTakenError(f"You already have a sound effect called {name!r}") from exc
        except BaseException:
            await self.session.rollback()
            await asyncio.to_thread(self.storage.delete, key)
            raise
        return effect

    async def _check_room(self, owner_id: UUID, name: str) -> None:
        count = await self.session.scalar(
            select(func.count()).select_from(SoundEffect).where(SoundEffect.user_id == owner_id)
        )
        if (count or 0) >= self.max_per_user:
            raise TooManySoundEffectsError(self.max_per_user)
        taken = await self.session.scalar(
            select(SoundEffect.id).where(SoundEffect.user_id == owner_id, SoundEffect.name == name)
        )
        if taken is not None:
            raise SoundEffectNameTakenError(f"You already have a sound effect called {name!r}")

    async def list_available(self, owner_id: UUID) -> list[SoundEffect]:
        """The user's own effects and the built-in ones: built-in first, then by name."""
        result = await self.session.exec(
            select(SoundEffect)
            .where(or_(col(SoundEffect.user_id) == owner_id, col(SoundEffect.user_id).is_(None)))
            .order_by(col(SoundEffect.user_id).is_not(None), col(SoundEffect.name))
        )
        return list(result.all())

    async def get_available(self, effect_id: UUID, owner_id: UUID) -> SoundEffect:
        """An effect the user may use (own or built in). Raises SoundEffectNotFoundError."""
        effect = await self.session.scalar(
            select(SoundEffect).where(
                SoundEffect.id == effect_id,
                or_(col(SoundEffect.user_id) == owner_id, col(SoundEffect.user_id).is_(None)),
            )
        )
        if effect is None:
            raise SoundEffectNotFoundError(f"No sound effect with id {effect_id}")
        return effect

    async def get_file(self, effect_id: UUID, owner_id: UUID) -> StoredSoundEffect:
        effect = await self.get_available(effect_id, owner_id)
        try:
            download = await asyncio.to_thread(self.storage.download, effect.file_path)
        except FileNotFoundError as exc:
            raise SoundEffectNotFoundError(f"The file for sound effect {effect_id} is missing") from exc
        suffix = PurePosixPath(effect.file_path).suffix
        return StoredSoundEffect(
            download=download,
            media_type=media_type_for(effect.file_path),
            download_filename=f"{effect.id}{suffix}",
        )

    async def delete(self, effect_id: UUID, owner_id: UUID) -> None:
        """Delete the user's own effect (not a built-in one).

        Raises SoundEffectNotFoundError, and SoundEffectInUseError while a
        pending or processing job uses it (it would fail when rendered).
        Finished jobs keep their audio; their sound_effect_id becomes NULL.
        """
        effect = await self.session.scalar(
            select(SoundEffect)
            .where(SoundEffect.id == effect_id, SoundEffect.user_id == owner_id)
            .with_for_update()
        )
        if effect is None:
            await self.session.commit()
            raise SoundEffectNotFoundError(f"No sound effect with id {effect_id}")
        in_use = await self.session.scalar(
            select(func.count())
            .select_from(AudioFile)
            .where(
                AudioFile.sound_effect_id == effect_id,
                col(AudioFile.status).in_((AudioStatus.PENDING, AudioStatus.PROCESSING)),
            )
        )
        if in_use:
            await self.session.commit()
            raise SoundEffectInUseError(
                f"{in_use} audio file(s) still being censored use this sound effect"
            )
        key = effect.file_path
        await self.session.delete(effect)
        await self.session.commit()
        await asyncio.to_thread(self.storage.delete, key)
