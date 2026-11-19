"""Where audio files live: local disk or S3-compatible object storage.

Everything else goes through `get_storage()`, which returns a Storage for
the configured STORAGE_BACKEND:

- `local` (default): files under STORAGE_DIR. The API and the worker must
  share that folder, so they must run on one machine.
- `s3`: an S3 bucket (AWS S3, or a compatible store such as MinIO). The API
  and any number of workers can then run on different machines.

Files are named by key, e.g. "uploads/<audio id>.mp3"; the `audio` table
stores those keys. Clients never see them.
"""

import logging
import mimetypes
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, BinaryIO, Protocol
from uuid import UUID

from app.config import settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:
    S3Client = Any

logger = logging.getLogger(__name__)

UPLOADS = "uploads"
CENSORED = "censored"

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


def input_suffix(filename: str | None) -> str:
    """Safe, lower-cased extension of an uploaded filename (default .wav)."""
    suffix = Path(filename or "").suffix.lower()
    return suffix if _SAFE_SUFFIX.fullmatch(suffix) else ".wav"


def output_suffix(in_suffix: str) -> str:
    """Extension to write the censored file with (see OUTPUT_MEDIA_TYPES)."""
    return in_suffix if in_suffix in OUTPUT_MEDIA_TYPES else ".wav"


def upload_key(audio_id: UUID, suffix: str) -> str:
    return f"{UPLOADS}/{audio_id}{suffix}"


def censored_key(audio_id: UUID, suffix: str) -> str:
    return f"{CENSORED}/{audio_id}{suffix}"


def media_type_for(key: str) -> str:
    """Content type for serving a stored file (originals may be any format)."""
    suffix = PurePosixPath(key).suffix.lower()
    return (
        OUTPUT_MEDIA_TYPES.get(suffix)
        or mimetypes.guess_type(f"x{suffix}")[0]
        or "application/octet-stream"
    )


def copy_limited(source: BinaryIO, dest: BinaryIO, max_bytes: int) -> None:
    """Copy in chunks, raising UploadTooLargeError once over max_bytes."""
    written = 0
    while chunk := source.read(_CHUNK_SIZE):
        written += len(chunk)
        if written > max_bytes:
            raise UploadTooLargeError(max_bytes)
        dest.write(chunk)


def remaining_size(source: BinaryIO) -> int | None:
    """Bytes left to read in `source`, or None if it can't seek."""
    try:
        if not source.seekable():
            return None
        position = source.tell()
        end = source.seek(0, 2)
        source.seek(position)
    except (AttributeError, OSError):
        return None
    return end - position


@dataclass(frozen=True)
class Download:
    """How to serve a stored file: a local path, or a stream of chunks.

    A stream must be closed (`close`) when done, also if the client stops
    reading part-way, so its connection to the storage is released.
    """

    path: Path | None = None
    chunks: Iterator[bytes] | None = None
    size: int | None = None
    close: Callable[[], None] | None = None


class Storage(Protocol):
    """All methods block (disk or network I/O): call them from a thread in
    async code, e.g. `await asyncio.to_thread(storage.delete, key)`."""

    def ensure_ready(self) -> None:
        """Create what's missing (folders, or the bucket if allowed); fail
        fast if the storage is unreachable."""
        ...

    def save(self, key: str, source: BinaryIO, max_bytes: int) -> None:
        """Store `source` under `key`. Raises UploadTooLargeError (nothing is
        kept) if it is longer than max_bytes."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, *keys: str) -> None:
        """Delete these files; missing ones are ignored."""
        ...

    def local_copy(self, key: str) -> AbstractContextManager[Path]:
        """A local file with the stored content, for tools that need a path
        (ffmpeg). Raises FileNotFoundError if `key` doesn't exist."""
        ...

    def local_output(self, key: str) -> AbstractContextManager[Path]:
        """A local path to write; stored under `key` if the block succeeds,
        discarded if it raises. If nothing was written, nothing is stored."""
        ...

    def download(self, key: str) -> Download:
        """How to serve `key`. Raises FileNotFoundError if it doesn't exist."""
        ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"Storage key escapes the storage folder: {key!r}")
        return path

    def ensure_ready(self) -> None:
        (self.root / UPLOADS).mkdir(parents=True, exist_ok=True)
        (self.root / CENSORED).mkdir(parents=True, exist_ok=True)

    def save(self, key: str, source: BinaryIO, max_bytes: int) -> None:
        dest = self.path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with dest.open("wb") as f:
                copy_limited(source, f, max_bytes)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.path(key).unlink(missing_ok=True)

    @contextmanager
    def local_copy(self, key: str) -> Iterator[Path]:
        path = self.path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        yield path

    @contextmanager
    def local_output(self, key: str) -> Iterator[Path]:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            yield path
        except BaseException:
            path.unlink(missing_ok=True)  # don't keep a partial file
            raise

    def download(self, key: str) -> Download:
        path = self.path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return Download(path=path)


class S3Storage:
    def __init__(self, client: S3Client, bucket: str, auto_create_bucket: bool = False):
        self.client = client
        self.bucket = bucket
        self.auto_create_bucket = auto_create_bucket

    def _is_missing(self, exc: Exception) -> bool:
        from botocore.exceptions import ClientError

        return isinstance(exc, ClientError) and exc.response.get("Error", {}).get(
            "Code"
        ) in (
            "404",
            "NoSuchKey",
            "NoSuchBucket",
            "NotFound",
        )

    def ensure_ready(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception as exc:
            if not (self._is_missing(exc) and self.auto_create_bucket):
                raise
            logger.info("Creating bucket %r", self.bucket)
            self.client.create_bucket(Bucket=self.bucket)

    def save(self, key: str, source: BinaryIO, max_bytes: int) -> None:
        extra = {"ContentType": media_type_for(key)}
        # An upload is usually already a seekable temporary file: check its
        # size and send it as it is, without another full copy.
        size = remaining_size(source)
        if size is not None:
            if size > max_bytes:
                raise UploadTooLargeError(max_bytes)
            self.client.upload_fileobj(source, self.bucket, key, ExtraArgs=extra)
            return
        # A stream of unknown length: copy it into a temporary file first,
        # so the size limit is enforced before anything reaches the bucket.
        with tempfile.TemporaryFile() as tmp:
            copy_limited(source, tmp, max_bytes)  # type: ignore[arg-type]
            tmp.seek(0)
            self.client.upload_fileobj(tmp, self.bucket, key, ExtraArgs=extra)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if self._is_missing(exc):
                return False
            raise
        return True

    def delete(self, *keys: str) -> None:
        if keys:
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True},
            )

    @contextmanager
    def local_copy(self, key: str) -> Iterator[Path]:
        tmp_dir = Path(tempfile.mkdtemp(prefix="audio-in-"))
        try:
            path = tmp_dir / PurePosixPath(key).name
            try:
                self.client.download_file(self.bucket, key, str(path))
            except Exception as exc:
                if self._is_missing(exc):
                    raise FileNotFoundError(key) from exc
                raise
            yield path
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @contextmanager
    def local_output(self, key: str) -> Iterator[Path]:
        tmp_dir = Path(tempfile.mkdtemp(prefix="audio-out-"))
        try:
            # Same file name as the key: ffmpeg picks the format from it.
            path = tmp_dir / PurePosixPath(key).name
            yield path
            if not path.exists():
                return  # nothing written, nothing to store
            self.client.upload_file(
                str(path),
                self.bucket,
                key,
                ExtraArgs={"ContentType": media_type_for(key)},
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def download(self, key: str) -> Download:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if self._is_missing(exc):
                raise FileNotFoundError(key) from exc
            raise
        body = obj["Body"]
        return Download(
            chunks=body.iter_chunks(_CHUNK_SIZE),
            size=obj["ContentLength"],
            close=body.close,
        )


@cache
def get_storage() -> Storage:
    """The configured storage, created once per process."""
    if settings.STORAGE_BACKEND == "s3":
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            # None falls back to boto3's usual credential chain (env vars,
            # ~/.aws, or an IAM role on AWS).
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=(
                settings.S3_SECRET_ACCESS_KEY.get_secret_value()
                if settings.S3_SECRET_ACCESS_KEY
                else None
            ),
            config=Config(
                # S3-compatible stores (MinIO) are addressed by path, not by
                # bucket subdomain.
                s3={"addressing_style": "path" if settings.S3_ENDPOINT_URL else "auto"},
                retries={"max_attempts": 5, "mode": "standard"},
            ),
        )
        return S3Storage(client, settings.S3_BUCKET, settings.S3_AUTO_CREATE_BUCKET)
    return LocalStorage(settings.storage_path)
