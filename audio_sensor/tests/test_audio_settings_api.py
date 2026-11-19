"""Censor settings over HTTP: on upload (POST /censor) and afterwards
(PATCH /audio/{id})."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.config import get_api_settings
from app.database.models import AudioFile, AudioStatus, CensorMode, JobStage, utc_now
from tests.helpers import (
    AppUser,
    FakeQueue,
    MakeUser,
    get_audio_row,
    make_audio,
    make_sound_effect,
    make_transcript,
    stored_keys,
)


def mp3() -> dict:
    return {"file": ("song.mp3", b"fake mp3 bytes", "audio/mpeg")}


async def finished_job(user: AppUser, **fields: Any) -> AudioFile:
    fields = {"stage": JobStage.RENDERED, "finished_at": utc_now() - timedelta(minutes=5)} | fields
    record = await make_audio(user.id, fields.pop("status", AudioStatus.COMPLETED), **fields)
    await make_transcript(record.id, [{"word": "hello", "start": 0.0, "end": 0.4}])
    return record


async def row(audio_id) -> AudioFile:
    record = await get_audio_row(audio_id)
    assert record is not None
    return record


# --- POST /censor ---------------------------------------------------------------------


async def test_upload_with_custom_words_and_mode(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    r = await client.post(
        "/censor",
        headers=user.headers,
        files=mp3(),
        data={"custom_words": ["Banana", "heck", "banana"], "censor_mode": "beep"},
    )

    assert r.status_code == 202
    body = r.json()
    assert body["custom_words"] == ["banana", "heck"]  # normalized
    assert (body["censor_mode"], body["sound_effect_id"], body["stage"]) == ("beep", None, None)
    assert queue.after == [None]  # all three steps
    stored = await row(UUID(body["id"]))
    assert (stored.custom_words, stored.censor_mode) == (["banana", "heck"], CensorMode.BEEP)


async def test_upload_defaults(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    body = (await client.post("/censor", headers=user.headers, files=mp3())).json()
    assert (body["custom_words"], body["censor_mode"], body["padding_ms"]) == ([], "mute", 150)


async def test_beep_flag_still_works(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    r = await client.post("/censor", headers=user.headers, files=mp3(), data={"beep": "true"})
    assert r.json()["censor_mode"] == "beep"


async def test_beep_flag_contradicting_the_mode_is_422(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    r = await client.post(
        "/censor", headers=user.headers, files=mp3(), data={"beep": "true", "censor_mode": "mute"}
    )
    assert r.status_code == 422
    assert queue.jobs == []


async def test_upload_with_own_sound_effect(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    effect = await make_sound_effect(user.id)
    r = await client.post(
        "/censor",
        headers=user.headers,
        files=mp3(),
        data={"censor_mode": "sound_effect", "sound_effect_id": str(effect.id)},
    )
    assert r.status_code == 202
    assert r.json()["sound_effect_id"] == str(effect.id)


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        ({"custom_words": ["ice cream"]}, "single words"),
        ({"custom_words": ["bad!"]}, "letters, digits"),
        ({"censor_mode": "sound_effect"}, "Choose a sound effect"),
        ({"sound_effect_id": "OTHERS"}, "only applies"),
        ({"censor_mode": "sound_effect", "sound_effect_id": "OTHERS"}, "No sound effect"),
        ({"censor_mode": "sound_effect", "sound_effect_id": str(uuid4())}, "No sound effect"),
    ],
    ids=["phrase", "bad-chars", "mode-without-effect", "effect-without-mode",
         "someone-elses-effect", "unknown-effect"],
)
async def test_bad_settings_on_upload_store_nothing(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue, data: dict, reason: str
) -> None:
    user, other = await make_user(), await make_user()
    if "OTHERS" in data.values():
        others = str((await make_sound_effect(other.id)).id)
        data = {k: (others if v == "OTHERS" else v) for k, v in data.items()}

    r = await client.post("/censor", headers=user.headers, files=mp3(), data=data)

    assert r.status_code == 422
    assert reason in r.json()["detail"]
    assert queue.jobs == []
    assert stored_keys("uploads") == []  # checked before storing anything


# --- PATCH /audio/{id} -------------------------------------------------------------------


async def test_patch_custom_words_reruns_detection(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    record = await finished_job(user)

    r = await client.patch(
        f"/audio/{record.id}", headers=user.headers, json={"custom_words": ["Banana"]}
    )

    assert r.status_code == 202
    body = r.json()
    assert (body["status"], body["stage"], body["custom_words"]) == (
        "pending", "transcribed", ["banana"],
    )
    assert body["censored_url"] is None  # not downloadable until re-rendered
    assert queue.after == [JobStage.TRANSCRIBED]


async def test_patch_mode_reruns_rendering_only(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    record = await finished_job(user)

    r = await client.patch(
        f"/audio/{record.id}", headers=user.headers, json={"censor_mode": "beep", "padding_ms": 250}
    )

    assert r.status_code == 202
    assert (r.json()["censor_mode"], r.json()["padding_ms"]) == ("beep", 250)
    assert queue.after == [JobStage.DETECTED]


async def test_patch_without_changes_is_200_and_queues_nothing(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    record = await finished_job(user, custom_words=["banana"])

    for body in ({}, {"custom_words": ["BANANA"]}, {"censor_mode": "mute"}):
        r = await client.patch(f"/audio/{record.id}", headers=user.headers, json=body)
        assert r.status_code == 200, body
        assert r.json()["status"] == "completed"
    assert queue.jobs == []


async def test_patch_empty_list_removes_custom_words(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await finished_job(user, custom_words=["banana"])

    r = await client.patch(f"/audio/{record.id}", headers=user.headers, json={"custom_words": []})

    assert r.status_code == 202 and r.json()["custom_words"] == []


@pytest.mark.parametrize(
    ("setup", "body", "code"),
    [
        ("busy", {"custom_words": ["banana"]}, 409),
        ("no-transcript", {"custom_words": ["banana"]}, 409),
        ("other-user", {"custom_words": ["banana"]}, 404),
        ("finished", {"custom_words": ["ice cream"]}, 422),
        ("finished", {"censor_mode": "sound_effect"}, 422),
        ("finished", {"padding_ms": 5000}, 422),
        ("finished", {"beep": True}, 422),  # unknown field
    ],
    ids=["busy", "no-transcript", "other-user", "phrase", "effect-mode-alone",
         "padding-too-big", "unknown-field"],
)
async def test_patch_refusals(
    client: httpx.AsyncClient,
    make_user: MakeUser,
    queue: FakeQueue,
    setup: str,
    body: dict,
    code: int,
) -> None:
    user, other = await make_user(), await make_user()
    if setup == "busy":
        record = await finished_job(user, status=AudioStatus.PROCESSING, stage=JobStage.TRANSCRIBED)
    elif setup == "no-transcript":
        record = await make_audio(user.id, AudioStatus.COMPLETED, stage=JobStage.RENDERED)
    elif setup == "other-user":
        record = await finished_job(other)
    else:
        record = await finished_job(user)

    r = await client.patch(f"/audio/{record.id}", headers=user.headers, json=body)

    assert r.status_code == code, r.text
    assert queue.jobs == []
    assert (await row(record.id)).status == record.status  # untouched


async def test_patch_with_queue_down_is_503_and_changes_nothing(
    client: httpx.AsyncClient, make_user: MakeUser, queue: FakeQueue
) -> None:
    user = await make_user()
    record = await finished_job(user)
    queue.available = False

    r = await client.patch(
        f"/audio/{record.id}", headers=user.headers, json={"custom_words": ["banana"]}
    )

    assert r.status_code == 503
    after = await row(record.id)
    assert (after.status, after.custom_words) == (AudioStatus.COMPLETED, [])


async def test_patch_at_the_active_jobs_cap_is_429(
    client: httpx.AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_api_settings(), "MAX_ACTIVE_JOBS_PER_USER", 1)
    user = await make_user()
    record = await finished_job(user)
    await make_audio(user.id)  # another job in progress

    r = await client.patch(
        f"/audio/{record.id}", headers=user.headers, json={"censor_mode": "beep"}
    )

    assert r.status_code == 429
    assert "Retry-After" in r.headers


async def test_patch_requires_login(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()
    record = await finished_job(user)
    r = await client.patch(f"/audio/{record.id}", json={"censor_mode": "beep"})
    assert r.status_code == 401


async def test_patch_shares_the_censor_rate_limit(
    client: httpx.AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_api_settings(), "CENSOR_RATE_LIMIT_PER_HOUR", 1)
    user = await make_user()
    record = await finished_job(user)

    assert (await client.post("/censor", headers=user.headers, files=mp3())).status_code == 202
    r = await client.patch(f"/audio/{record.id}", headers=user.headers, json={"censor_mode": "beep"})
    assert r.status_code == 429
