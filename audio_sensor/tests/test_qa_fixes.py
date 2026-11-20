"""Regression tests for the QA findings: 8 bugs and 4 gaps. Each test is
named after what it guards; the QA report numbers are in the section titles."""

import asyncio
import io
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from pydub import AudioSegment
from pydub.generators import Sine
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_audio_service, get_current_user
from app.api.routers import health
from app.audio_censor import AudioCensor, AudioTooLongError, Word, _load_audio
from app.config import settings
from app.database.models import AudioStatus, CensorMode, JobStage, SoundEffect, User
from app.database.session import async_session_maker
from app.main import app
from app.service.audio_service import (
    AudioService,
    SoundEffectNotFoundError,
    StoredAudioFile,
)
from app.storage import Download
from tests.helpers import (
    FakeQueue,
    MakeUser,
    get_audio_row,
    helper_engine,
    helper_sessions,
    make_audio,
    make_sound_effect,
    make_transcript,
    stored_keys,
)


def wav(ms: int, rate: int = 16000, freq: int = 440) -> bytes:
    buf = io.BytesIO()
    (
        Sine(freq, sample_rate=rate)
        .to_audio_segment(duration=ms, volume=-10)
        .set_sample_width(1 if rate <= 8000 else 2)
        .export(buf, format="wav")
    )
    return buf.getvalue()


def wav_file(tmp_path: Path, name: str, ms: int, freq: int = 440) -> Path:
    path = tmp_path / name
    path.write_bytes(wav(ms, freq=freq))
    return path


# --- Bug 1: audio duration is limited, not only file size ------------------------------


async def test_upload_whose_headers_declare_too_long_is_refused(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "MAX_AUDIO_MINUTES", 1)
    user = await make_user()
    long_wav = wav(61_000, rate=8000)  # 61 s, but only ~0.5 MB

    r = await client.post(
        "/censor", headers=user.headers, files={"file": ("long.wav", long_wav, "audio/wav")}
    )

    assert r.status_code == 422
    assert "at most 1 minutes" in r.json()["detail"]
    assert queue.jobs == [] and stored_keys("uploads") == []


def test_decoding_never_reads_past_the_limit(tmp_path: Path) -> None:
    """Even if headers lie, the worker decodes at most max_seconds + 1."""
    path = wav_file(tmp_path, "three_seconds.wav", 3000)

    audio = _load_audio(str(path), max_seconds=1)
    assert len(audio) <= 2 * 16000  # stopped after ~2 s, not all 3

    with pytest.raises(AudioTooLongError):
        AudioCensor._decode(str(path), max_seconds=1)
    assert len(AudioCensor._decode(str(path), max_seconds=5)) == pytest.approx(3 * 16000, rel=0.02)


def test_sound_effects_are_decoded_only_up_to_their_limit(tmp_path: Path) -> None:
    effect = wav_file(tmp_path, "effect.wav", 3000)
    target = AudioSegment.from_file(wav_file(tmp_path, "song.wav", 1000))

    loaded = AudioCensor(max_effect_seconds=1)._load_effect(str(effect), target)

    assert len(loaded) <= 1000


# --- Bug 2: flagged words without timestamps are still censored -------------------------


def silent_ranges(path: str) -> list[tuple[int, int]]:
    """Silent stretches (50 ms resolution) of a file, as (start_ms, end_ms)."""
    audio = AudioSegment.from_file(path)
    ranges: list[tuple[int, int]] = []
    for i in range(0, len(audio), 50):
        if audio[i : i + 50].rms == 0:
            if ranges and ranges[-1][1] == i:
                ranges[-1] = (ranges[-1][0], i + 50)
            else:
                ranges.append((i, i + 50))
    return ranges


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        # Gap between the neighbours (0.4 - 1.6 s): censor the gap.
        (
            [Word(word="hello", start=0.1, end=0.4), Word(word="1984", flagged=True),
             Word(word="there", start=1.6, end=1.9)],
            (400, 1600),
        ),
        # Neighbours leave no room (0.4 - 0.45 s): include them too.
        (
            [Word(word="hello", start=0.1, end=0.4), Word(word="1984", flagged=True),
             Word(word="there", start=0.45, end=0.9)],
            (100, 900),
        ),
        # No timed words at all: the whole file.
        ([Word(word="1984", flagged=True)], (0, 2000)),
    ],
    ids=["gap", "no-gap", "nothing-timed"],
)
def test_flagged_word_without_timestamps_is_censored(
    tmp_path: Path, words: list[Word], expected: tuple[int, int]
) -> None:
    src = wav_file(tmp_path, "in.wav", 2000)

    out = AudioCensor().render_audio(str(src), words, str(tmp_path / "out.wav"), padding_ms=0)

    assert out is not None
    (start, end), *rest = silent_ranges(out)
    assert not rest
    assert abs(start - expected[0]) <= 50 and abs(end - expected[1]) <= 50


# --- Bug 3: login accepts the email exactly as typed at signup --------------------------


async def test_login_with_the_email_as_typed_at_signup(client: httpx.AsyncClient) -> None:
    typed = "  Jane.Doe@Example.COM  "
    r = await client.post("/auth/signup", json={"email": typed, "password": "correct-horse-42"})
    assert r.status_code == 201

    for username in (typed, typed.strip(), "jane.doe@example.com"):
        r = await client.post("/auth/login", data={"username": username, "password": "correct-horse-42"})
        assert r.status_code == 200, username


# --- Bug 4: effect deleted during a PATCH is a 422, not a 500 ----------------------------


async def test_effect_deleted_while_patching(
    make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await make_user()
    effect = await make_sound_effect(user.id, wav(200))
    record = await make_audio(user.id, AudioStatus.COMPLETED, stage=JobStage.RENDERED)
    await make_transcript(record.id, [{"word": "hi", "start": 0.0, "end": 0.2}])

    real_check = AudioService._check_sound_effect

    async def check_then_effect_vanishes(self, effect_id, owner_id):
        await real_check(self, effect_id, owner_id)
        async with helper_engine.begin() as conn:  # another request deletes it now
            await conn.execute(text("DELETE FROM sound_effects WHERE id = :id"), {"id": effect_id})

    monkeypatch.setattr(AudioService, "_check_sound_effect", check_then_effect_vanishes)
    queue = FakeQueue()
    async with async_session_maker() as session:
        with pytest.raises(SoundEffectNotFoundError):
            await AudioService(session, queue).update_settings(
                record.id, user.id, censor_mode=CensorMode.SOUND_EFFECT, sound_effect_id=effect.id
            )
    assert queue.jobs == []
    after = await get_audio_row(record.id)
    assert after is not None and (after.status, after.censor_mode) == (
        AudioStatus.COMPLETED, CensorMode.MUTE,
    )


# --- Bug 5: a clear message when the job's effect was deleted -----------------------------


async def test_patch_after_the_jobs_effect_was_deleted_says_so(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await make_audio(
        user.id, AudioStatus.COMPLETED, stage=JobStage.RENDERED, censor_mode=CensorMode.SOUND_EFFECT
    )  # sound_effect_id NULL: its effect was deleted
    await make_transcript(record.id, [{"word": "hi", "start": 0.0, "end": 0.2}])

    r = await client.patch(f"/audio/{record.id}", headers=user.headers, json={"padding_ms": 400})

    assert r.status_code == 422
    assert "sound effect was deleted" in r.json()["detail"]


# --- Bug 6: sound-effect names are unique ignoring case -----------------------------------


async def test_effect_names_differing_only_in_case_are_one_name(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    files = {"file": ("a.wav", wav(200), "audio/wav")}
    assert (await client.post("/sound-effects", headers=user.headers, files=files, data={"name": "Airhorn"})).status_code == 201
    for name in ("airhorn", "AIRHORN"):
        r = await client.post("/sound-effects", headers=user.headers, files=files, data={"name": name})
        assert r.status_code == 409, name


async def test_database_enforces_case_insensitive_names(make_user: MakeUser) -> None:
    user = await make_user()
    async with helper_sessions() as s:
        s.add(SoundEffect(user_id=user.id, name="Bell", file_path="effects/a.wav"))
        await s.commit()
        s.add(SoundEffect(user_id=user.id, name="BELL", file_path="effects/b.wav"))
        with pytest.raises(IntegrityError):
            await s.commit()


# --- Bug 7: a download's bytes match its extension ---------------------------------------


def test_clean_file_whose_extension_lies_is_converted_not_reused(tmp_path: Path) -> None:
    lying = tmp_path / "tone.mp3"
    lying.write_bytes(wav(1000))  # WAV data named .mp3
    honest = tmp_path / "real.mp3"
    AudioSegment.from_file(io.BytesIO(wav(1000))).export(honest, format="mp3")
    clean = [Word(word="hello", start=0.1, end=0.4, flagged=False)]
    censor = AudioCensor()

    # A real MP3 with nothing to censor: reused as it is.
    assert censor.render_audio(str(honest), clean, str(tmp_path / "o1.mp3"), copy_unchanged=False) is None

    # WAV bytes named .mp3: converted, so the output really is MP3.
    out = censor.render_audio(str(lying), clean, str(tmp_path / "o2.mp3"), copy_unchanged=False)
    assert out is not None
    head = Path(out).read_bytes()[:4]
    assert not head.startswith(b"RIFF")
    assert head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


# --- Bug 8 is covered in test_sound_effects_api.py (non-audio content, too long, webm) ----


# --- Gap 1: CORS for browser front-ends ---------------------------------------------------


async def test_cors_preflight_from_an_allowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.options(
        "/audio",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://app.example.com"
    assert "PATCH" in r.headers["access-control-allow-methods"]


async def test_cors_refuses_other_origins(client: httpx.AsyncClient) -> None:
    r = await client.options(
        "/audio",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in r.headers


async def test_cors_exposes_the_headers_clients_read(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    r = await client.get(
        "/audio", headers={**user.headers, "Origin": "https://app.example.com"}
    )
    exposed = r.headers["access-control-expose-headers"].lower()
    for header in ("location", "x-next-cursor", "retry-after", "content-disposition"):
        assert header in exposed


# --- Gap 2: health check ------------------------------------------------------------------


async def ok() -> None:
    return None


async def down() -> None:
    raise ConnectionError("secret internal detail")


async def hangs() -> None:
    await asyncio.sleep(30)


async def test_health_ok(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # The database check is real; Redis isn't needed by the test suite.
    monkeypatch.setitem(health.CHECKS, "redis", ok)
    r = await client.get("/health")  # no login needed
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


@pytest.mark.parametrize("failure", [down, hangs], ids=["error", "timeout"])
async def test_health_reports_an_unreachable_dependency(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, failure
) -> None:
    monkeypatch.setitem(health.CHECKS, "redis", failure)
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.5)

    r = await client.get("/health")

    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "checks": {"database": "ok", "redis": "unavailable"}}
    assert "secret" not in r.text


# --- Gap 3: HEAD on downloads ---------------------------------------------------------------


async def test_head_on_a_local_download(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    record = await make_audio(user.id, AudioStatus.COMPLETED, censored=b"12345")

    r = await client.head(f"/audio/{record.id}/file", headers=user.headers)

    assert r.status_code == 200
    assert r.headers["content-length"] == "5"
    assert r.content == b""


async def test_head_on_a_streamed_download_closes_it_unread() -> None:
    closed: list[bool] = []

    class Service:
        async def get_audio_file(self, audio_id, owner_id, variant=None):
            return StoredAudioFile(
                download=Download(chunks=iter([b"x" * 10]), size=10, close=lambda: closed.append(True)),
                media_type="audio/mpeg",
                download_filename="a.mp3",
            )

    app.dependency_overrides[get_audio_service] = lambda: Service()
    app.dependency_overrides[get_current_user] = lambda: User(id=uuid4(), email="a@b.c", hashed_password="x")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.head(f"/audio/{uuid4()}/file")
    finally:
        app.dependency_overrides.pop(get_audio_service, None)
        app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 200
    assert r.headers["content-length"] == "10" and r.content == b""
    assert closed == [True]


async def test_head_on_a_sound_effect(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    effect = await make_sound_effect(user.id, wav(200))
    r = await client.head(f"/sound-effects/{effect.id}/file", headers=user.headers)
    assert r.status_code == 200 and int(r.headers["content-length"]) > 0 and r.content == b""


# --- Gap 4: the transcript, with what was censored -------------------------------------------


async def test_transcript_shows_the_censored_words(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await make_audio(user.id, AudioStatus.COMPLETED, stage=JobStage.RENDERED)
    await make_transcript(record.id, [
        {"word": "hello", "start": 0.0, "end": 0.4, "score": 0.9, "flagged": False},
        {"word": "darn", "start": 0.5, "end": 0.9, "score": 0.8, "flagged": True},
        {"word": "1984", "flagged": False},
    ])

    r = await client.get(f"/audio/{record.id}/transcript", headers=user.headers)

    assert r.status_code == 200
    body = r.json()
    assert (UUID(body["audio_id"]), body["stage"]) == (record.id, "rendered")
    assert [(w["word"], w["flagged"]) for w in body["words"]] == [
        ("hello", False), ("darn", True), ("1984", False),
    ]
    assert body["words"][2]["start"] is None  # the aligner couldn't place it


async def test_transcript_before_detection_has_no_flags(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await make_audio(user.id, AudioStatus.PROCESSING, stage=JobStage.TRANSCRIBED)
    await make_transcript(record.id, [{"word": "hello", "start": 0.0, "end": 0.4}])

    body = (await client.get(f"/audio/{record.id}/transcript", headers=user.headers)).json()

    assert body["stage"] == "transcribed" and body["words"][0]["flagged"] is None


@pytest.mark.parametrize(
    ("status", "code"),
    [(AudioStatus.PENDING, 409), (AudioStatus.PROCESSING, 409), (AudioStatus.COMPLETED, 404)],
)
async def test_transcript_not_available(
    client: httpx.AsyncClient, make_user: MakeUser, status: AudioStatus, code: int
) -> None:
    user = await make_user()
    record = await make_audio(user.id, status)  # no transcript row

    r = await client.get(f"/audio/{record.id}/transcript", headers=user.headers)

    assert r.status_code == code


async def test_other_users_transcript_is_not_found(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    owner, other = await make_user(), await make_user()
    record = await make_audio(owner.id, AudioStatus.COMPLETED, stage=JobStage.RENDERED)
    await make_transcript(record.id, [{"word": "secret", "start": 0.0, "end": 0.4}])

    r = await client.get(f"/audio/{record.id}/transcript", headers=other.headers)

    assert r.status_code == 404 and "secret" not in r.text
