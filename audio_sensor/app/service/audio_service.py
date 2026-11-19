import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlmodel.ext.asyncio.session import AsyncSession

from app.audio_censor import AudioCensor, Word
from app.config import settings
from app.database.models import AudioFile
from app.storage import (
    CENSORED_DIR,
    OUTPUT_MEDIA_TYPES,
    UPLOADS_DIR,
    delete_files,
    input_suffix,
    media_type_for,
    output_suffix,
    resolve_stored_path,
    save_upload,
    to_stored_path,
)


class AudioNotFoundError(LookupError):
    """No `audio` record with that ID, or its file is missing from storage."""


class AudioVariant(StrEnum):
    CENSORED = "censored"
    ORIGINAL = "original"


@dataclass
class StoredAudioFile:
    path: Path
    media_type: str
    download_filename: str


@dataclass
class CensorResult:
    record: AudioFile
    words: list[Word]
    media_type: str
    download_filename: str  # suggested name for the client, e.g. "song_censored.mp3"

    @property
    def censored_path(self) -> Path:
        return resolve_stored_path(self.record.censored_file_path)

    @property
    def flagged_count(self) -> int:
        return sum(w["flagged"] for w in self.words)


class AudioService:
    """Censors uploaded audio and stores the result (files + `audio` row).

    Knows nothing about HTTP, so it can be reused from scripts or tests.
    """

    def __init__(
        self,
        session: AsyncSession,
        censor: AudioCensor,
        max_upload_bytes: int = settings.max_upload_bytes,
    ):
        self.session = session
        self.censor = censor
        self.max_upload_bytes = max_upload_bytes

    async def censor_upload(
        self,
        filename: str | None,
        data: BinaryIO,
        padding_ms: int = 150,
        beep: bool = False,
    ) -> CensorResult:
        """Save the upload, censor it, and record both files in the database.

        Nothing is kept unless both files and the DB row were written: on any
        failure the transaction is rolled back and the files are deleted.
        Raises UploadTooLargeError if the upload exceeds the size limit, and
        AudioDecodeError if it isn't decodable audio.

        The blocking parts (file I/O and the CPU-heavy censoring) run in a
        worker thread so they don't stall the event loop for other requests.
        """
        in_suffix = input_suffix(filename)
        out_suffix = output_suffix(in_suffix)

        # Files are named by the record's ID, so names never collide and the
        # client's filename is never used as a path.
        audio_id = uuid4()
        src = UPLOADS_DIR / f"{audio_id}{in_suffix}"
        out = CENSORED_DIR / f"{audio_id}{out_suffix}"

        try:
            await asyncio.to_thread(save_upload, data, src, self.max_upload_bytes)
            _, words = await asyncio.to_thread(
                self.censor.censor_audio,
                str(src),
                output_path=str(out),
                padding_ms=padding_ms,
                beep=beep,
            )

            record = AudioFile(
                id=audio_id,
                file_path=to_stored_path(src),
                censored_file_path=to_stored_path(out),
            )
            self.session.add(record)
            await self.session.commit()
            # No refresh(): every field is set in Python, and anything that
            # could fail after commit must not reach the cleanup below, or it
            # would delete the files of a row that was already saved.
        except BaseException:
            await self.session.rollback()
            delete_files(src, out)
            raise

        return CensorResult(
            record=record,
            words=words,
            media_type=OUTPUT_MEDIA_TYPES[out_suffix],
            download_filename=f"{Path(filename or 'audio').stem}_censored{out_suffix}",
        )

    async def get_audio(self, audio_id: UUID) -> AudioFile:
        """The `audio` record for this ID. Raises AudioNotFoundError."""
        record = await self.session.get(AudioFile, audio_id)
        if record is None:
            raise AudioNotFoundError(f"No audio with id {audio_id}")
        return record

    async def get_audio_file(
        self, audio_id: UUID, variant: AudioVariant = AudioVariant.CENSORED
    ) -> StoredAudioFile:
        """The censored or original file of a stored record.

        Raises AudioNotFoundError if the record doesn't exist or its file has
        been removed from storage.
        """
        record = await self.get_audio(audio_id)
        stored = (
            record.censored_file_path
            if variant is AudioVariant.CENSORED
            else record.file_path
        )
        path = resolve_stored_path(stored)
        if not path.is_file():
            raise AudioNotFoundError(f"The {variant} file for audio {audio_id} is missing")

        # The client's original filename isn't stored, so name downloads by ID.
        suffix = "_censored" if variant is AudioVariant.CENSORED else ""
        return StoredAudioFile(
            path=path,
            media_type=media_type_for(path),
            download_filename=f"{audio_id}{suffix}{path.suffix}",
        )
