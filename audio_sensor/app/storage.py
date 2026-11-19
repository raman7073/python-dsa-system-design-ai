"""Where audio files live on disk, and helpers to read/write them safely."""

import mimetypes
import re
from pathlib import Path
from typing import BinaryIO

from app.config import settings

UPLOADS_DIR = settings.storage_path / "uploads"
CENSORED_DIR = settings.storage_path / "censored"

# Output keeps the upload's format when pydub/ffmpeg can write it directly;
# anything else (e.g. .m4a, .webm) comes back as WAV.
OUTPUT_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}

# Accept only plain extensions like ".mp3" from client filenames; rejects
# oddities such as ".wav:stream" (an NTFS alternate data stream), trailing
# spaces, or very long suffixes.
_SAFE_SUFFIX = re.compile(r"\.[a-z0-9]{1,5}")
_CHUNK_SIZE = 1024 * 1024


class UploadTooLargeError(ValueError):
    """The upload exceeded the configured size limit."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        super().__init__(f"Upload exceeds {max_bytes // (1024 * 1024)} MB")


def ensure_storage_dirs() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    CENSORED_DIR.mkdir(parents=True, exist_ok=True)


def input_suffix(filename: str | None) -> str:
    """Safe, lower-cased extension of an uploaded filename (default .wav)."""
    suffix = Path(filename or "").suffix.lower()
    return suffix if _SAFE_SUFFIX.fullmatch(suffix) else ".wav"


def output_suffix(in_suffix: str) -> str:
    """Extension to write the censored file with (see OUTPUT_MEDIA_TYPES)."""
    return in_suffix if in_suffix in OUTPUT_MEDIA_TYPES else ".wav"


def save_upload(source: BinaryIO, dest: Path, max_bytes: int) -> None:
    """Stream an upload to disk in chunks, stopping once it exceeds max_bytes.

    Raises UploadTooLargeError; the partial file is left for the caller to
    delete along with anything else it created.
    """
    written = 0
    with dest.open("wb") as f:
        while chunk := source.read(_CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                raise UploadTooLargeError(max_bytes)
            f.write(chunk)


def media_type_for(path: Path) -> str:
    """Content type for serving a stored file (originals may be any format)."""
    return (
        OUTPUT_MEDIA_TYPES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


def to_stored_path(path: Path) -> str:
    """Path as saved in the database: relative to STORAGE_DIR, e.g.
    "censored/<id>.mp3", so rows stay valid if the storage folder moves."""
    return path.relative_to(settings.storage_path).as_posix()


def resolve_stored_path(stored: str) -> Path:
    """Inverse of to_stored_path(). Absolute paths (rows written before paths
    were stored relative) are returned unchanged."""
    return settings.storage_path / stored


def delete_files(*paths: Path) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
