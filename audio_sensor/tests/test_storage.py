"""Both storage backends must behave the same.

The S3 cases run against an S3-compatible server at TEST_S3_ENDPOINT_URL
(default http://127.0.0.1:8333, the `s3` service in docker-compose.yml:
`docker compose --profile s3 up -d s3`) and are skipped if none is running.
"""

import io
import os
import socket
import tempfile
import uuid
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.storage import LocalStorage, S3Storage, Storage, UploadTooLargeError

S3_ENDPOINT = os.environ.get("TEST_S3_ENDPOINT_URL", "http://127.0.0.1:8333")


@cache
def s3_server_up() -> bool:
    """Checked once per run, so with no server every S3 test skips at once
    instead of each waiting out a connection timeout."""
    url = urlsplit(S3_ENDPOINT)
    try:
        socket.create_connection((url.hostname, url.port or 80), timeout=1).close()
    except OSError:
        return False
    return True


def skip_without_s3() -> None:
    if not s3_server_up():
        pytest.skip(f"No S3-compatible server at {S3_ENDPOINT}")


def _s3_storage() -> S3Storage:
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name="us-east-1",
        aws_access_key_id="dev",
        aws_secret_access_key="dev-secret",
        config=Config(
            s3={"addressing_style": "path"},
            connect_timeout=2,
            retries={"max_attempts": 1},
        ),
    )
    return S3Storage(client, f"test-{uuid.uuid4().hex[:12]}", auto_create_bucket=True)


@pytest.fixture(params=["local", "s3"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Storage]:
    if request.param == "local":
        local = LocalStorage(tmp_path)
        local.ensure_ready()
        yield local
        return

    skip_without_s3()
    s3 = _s3_storage()
    s3.ensure_ready()
    yield s3
    # Empty and remove the throwaway bucket.
    listed = s3.client.list_objects_v2(Bucket=s3.bucket).get("Contents", [])
    s3.delete(*[obj["Key"] for obj in listed if "Key" in obj])
    s3.client.delete_bucket(Bucket=s3.bucket)


def test_save_exists_download(storage: Storage) -> None:
    storage.save("uploads/a.mp3", io.BytesIO(b"hello"), max_bytes=100)

    assert storage.exists("uploads/a.mp3")
    assert not storage.exists("uploads/missing.mp3")
    download = storage.download("uploads/a.mp3")
    if download.path is not None:
        assert download.path.read_bytes() == b"hello"
    else:
        assert b"".join(download.chunks or []) == b"hello"
        assert download.size == 5


def test_save_over_limit_keeps_nothing(storage: Storage) -> None:
    with pytest.raises(UploadTooLargeError):
        storage.save("uploads/big.mp3", io.BytesIO(b"x" * 101), max_bytes=100)
    assert not storage.exists("uploads/big.mp3")


def test_local_copy_gives_a_readable_file(storage: Storage) -> None:
    storage.save("uploads/a.mp3", io.BytesIO(b"hello"), max_bytes=100)
    with storage.local_copy("uploads/a.mp3") as path:
        assert path.read_bytes() == b"hello"
        assert path.suffix == ".mp3"  # ffmpeg relies on the extension


def test_local_copy_of_missing_key_raises(storage: Storage) -> None:
    with pytest.raises(FileNotFoundError), storage.local_copy("uploads/missing.mp3"):
        pass


def test_local_output_is_stored_on_success(storage: Storage) -> None:
    with storage.local_output("censored/a.mp3") as path:
        assert path.suffix == ".mp3"
        path.write_bytes(b"beeped")
    assert storage.exists("censored/a.mp3")


def test_local_output_is_discarded_on_error(storage: Storage) -> None:
    with pytest.raises(RuntimeError), storage.local_output("censored/a.mp3") as path:
        path.write_bytes(b"partial")
        raise RuntimeError("censoring failed")
    assert not storage.exists("censored/a.mp3")


def test_delete_ignores_missing_keys(storage: Storage) -> None:
    storage.save("uploads/a.mp3", io.BytesIO(b"hello"), max_bytes=100)
    storage.delete("uploads/a.mp3", "uploads/never-existed.mp3")
    assert not storage.exists("uploads/a.mp3")


def test_download_of_missing_key_raises(storage: Storage) -> None:
    with pytest.raises(FileNotFoundError):
        storage.download("uploads/missing.mp3")


def test_local_keys_cannot_escape_the_folder(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "root")
    with pytest.raises(ValueError, match="escapes"):
        storage.save("../outside.mp3", io.BytesIO(b"x"), max_bytes=10)


class Unseekable:
    """A stream of unknown length, like a network body."""

    def __init__(self, data: bytes):
        self._data = io.BytesIO(data)

    def read(self, size: int = -1) -> bytes:
        return self._data.read(size)

    def seekable(self) -> bool:
        return False


def test_save_of_unseekable_stream(storage: Storage) -> None:
    storage.save("uploads/s.mp3", Unseekable(b"streamed"), max_bytes=100)  # type: ignore[arg-type]
    with storage.local_copy("uploads/s.mp3") as path:
        assert path.read_bytes() == b"streamed"


def test_save_over_limit_of_unseekable_stream_keeps_nothing(storage: Storage) -> None:
    with pytest.raises(UploadTooLargeError):
        storage.save("uploads/big.mp3", Unseekable(b"x" * 101), max_bytes=100)  # type: ignore[arg-type]
    assert not storage.exists("uploads/big.mp3")


def test_s3_uploads_a_seekable_source_as_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """No extra temporary copy for the usual case (an already-spooled upload)."""
    skip_without_s3()
    s3 = _s3_storage()
    s3.ensure_ready()
    sent: list[object] = []
    real_upload = s3.client.upload_fileobj

    def spy(fileobj, *args, **kwargs):
        sent.append(fileobj)
        return real_upload(fileobj, *args, **kwargs)

    monkeypatch.setattr(s3.client, "upload_fileobj", spy)
    temp_files: list[object] = []
    real_tempfile = tempfile.TemporaryFile
    monkeypatch.setattr(
        tempfile, "TemporaryFile", lambda *a, **k: temp_files.append(1) or real_tempfile(*a, **k)
    )
    source = io.BytesIO(b"hello")
    try:
        s3.save("uploads/a.mp3", source, max_bytes=100)
        assert sent == [source]  # the caller's file, not a copy
        assert temp_files == []
        with pytest.raises(UploadTooLargeError):
            s3.save("uploads/big.mp3", io.BytesIO(b"x" * 101), max_bytes=100)
        assert len(sent) == 1  # refused before uploading anything
    finally:
        listed = s3.client.list_objects_v2(Bucket=s3.bucket).get("Contents", [])
        s3.delete(*[obj["Key"] for obj in listed if "Key" in obj])
        s3.client.delete_bucket(Bucket=s3.bucket)


def test_local_output_with_nothing_written_stores_nothing(storage: Storage) -> None:
    with storage.local_output("censored/a.mp3"):
        pass
    assert not storage.exists("censored/a.mp3")


def test_s3_download_can_be_closed(storage: Storage) -> None:
    storage.save("uploads/a.mp3", io.BytesIO(b"hello"), max_bytes=100)
    download = storage.download("uploads/a.mp3")
    if download.path is not None:
        assert download.close is None  # a local file needs no closing
        return
    assert download.close is not None
    download.close()
