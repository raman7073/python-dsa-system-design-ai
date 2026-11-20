"""Both storage backends must behave the same.

The S3 cases run against moto's in-memory S3 (no server, no network, never
a real bucket): every test gets a fresh, empty bucket.
"""

import io
import logging
import tempfile
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from app.storage import LocalStorage, S3Storage, Storage, UploadTooLargeError

BUCKET = "test-bucket"


def _s3_storage(region: str = "us-east-1", auto_create: bool = True) -> S3Storage:
    # Fake credentials: inside mock_aws nothing leaves the process, and the
    # real ones (.env, ~/.aws) are never used.
    client = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    return S3Storage(client, BUCKET, auto_create_bucket=auto_create)


@pytest.fixture
def s3() -> Iterator[S3Storage]:
    with mock_aws():
        storage = _s3_storage()
        storage.ensure_ready()
        yield storage


@pytest.fixture(params=["local", "s3"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[Storage]:
    if request.param == "local":
        local = LocalStorage(tmp_path)
        local.ensure_ready()
        yield local
        return
    with mock_aws():
        s3 = _s3_storage()
        s3.ensure_ready()
        yield s3


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


def test_s3_uploads_a_seekable_source_as_is(
    s3: S3Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No extra temporary copy for the usual case (an already-spooled upload)."""
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

    s3.save("uploads/a.mp3", source, max_bytes=100)
    assert sent == [source]  # the caller's file, not a copy
    assert temp_files == []
    with pytest.raises(UploadTooLargeError):
        s3.save("uploads/big.mp3", io.BytesIO(b"x" * 101), max_bytes=100)
    assert len(sent) == 1  # refused before uploading anything


def test_s3_stores_the_content_type(s3: S3Storage) -> None:
    s3.save("uploads/a.mp3", io.BytesIO(b"hello"), max_bytes=100)
    head = s3.client.head_object(Bucket=BUCKET, Key="uploads/a.mp3")
    assert head["ContentType"] == "audio/mpeg"


@pytest.mark.parametrize("region", ["us-east-1", "ap-southeast-2"])
def test_s3_creates_a_missing_bucket_in_its_region(region: str) -> None:
    # Outside us-east-1, AWS refuses a create without the LocationConstraint.
    with mock_aws():
        storage = _s3_storage(region)
        storage.ensure_ready()
        storage.ensure_ready()  # already there: nothing to do
        location = storage.client.get_bucket_location(Bucket=BUCKET)["LocationConstraint"]
        assert (location or "us-east-1") == region


def test_s3_missing_bucket_fails_without_auto_create() -> None:
    from botocore.exceptions import ClientError

    with mock_aws(), pytest.raises(ClientError):
        _s3_storage(auto_create=False).ensure_ready()


def test_s3_denied_bucket_fails_startup_with_a_clear_message(
    s3: S3Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    from botocore.exceptions import ClientError

    def forbidden(**kwargs):
        raise ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadBucket")

    monkeypatch.setattr(s3.client, "head_bucket", forbidden)
    with pytest.raises(PermissionError, match="s3:ListBucket"):
        s3.ensure_ready()


def test_s3_refused_deletes_are_logged(
    s3: S3Storage, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # S3 reports per-key failures in the response body, not as an exception.
    monkeypatch.setattr(
        s3.client,
        "delete_objects",
        lambda **kw: {"Errors": [{"Key": "uploads/a.mp3", "Code": "AccessDenied"}]},
    )
    with caplog.at_level(logging.ERROR, logger="app.storage"):
        s3.delete("uploads/a.mp3")
    assert "uploads/a.mp3 (AccessDenied)" in caplog.text


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
