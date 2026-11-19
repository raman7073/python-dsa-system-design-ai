"""The /sound-effects endpoints, and using an uploaded effect for censoring."""

from uuid import UUID, uuid4

import httpx
import pytest

from app.config import get_api_settings
from app.database.models import AudioStatus, CensorMode
from tests.helpers import (
    MakeUser,
    get_audio_row,
    make_audio,
    make_sound_effect,
    read_stored,
    stored_keys,
)


def effect_file(content: bytes = b"honk", filename: str = "honk.wav") -> dict:
    return {"file": (filename, content, "audio/wav")}


async def upload(client: httpx.AsyncClient, headers: dict, name: str = "honk", **kwargs):
    return await client.post(
        "/sound-effects", headers=headers, files=effect_file(**kwargs), data={"name": name}
    )


async def test_upload_list_preview_delete(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user = await make_user()

    r = await upload(client, user.headers, name="  Air horn ")
    assert r.status_code == 201
    effect = r.json()
    assert (effect["name"], effect["built_in"]) == ("Air horn", False)  # trimmed
    assert r.headers["Location"].endswith(f"/sound-effects/{effect['id']}/file")
    assert stored_keys("effects") == [f"effects/{effect['id']}.wav"]

    listed = (await client.get("/sound-effects", headers=user.headers)).json()
    assert [e["id"] for e in listed] == [effect["id"]]

    preview = await client.get(effect["file_url"].removeprefix("http://test"), headers=user.headers)
    assert preview.status_code == 200
    assert preview.content == b"honk"
    assert preview.headers["content-type"] == "audio/wav"

    r = await client.delete(f"/sound-effects/{effect['id']}", headers=user.headers)
    assert r.status_code == 204
    assert (await client.get("/sound-effects", headers=user.headers)).json() == []
    assert stored_keys("effects") == []  # the file is gone too


async def test_list_shows_built_in_first_then_own_and_never_others(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user, other = await make_user(), await make_user()
    await make_sound_effect(None, name="classic bleep")
    await make_sound_effect(other.id, name="theirs")
    await upload(client, user.headers, name="zebra")
    await upload(client, user.headers, name="alpha")

    listed = (await client.get("/sound-effects", headers=user.headers)).json()

    assert [(e["name"], e["built_in"]) for e in listed] == [
        ("classic bleep", True), ("alpha", False), ("zebra", False),
    ]


async def test_built_in_effect_can_be_previewed_not_deleted(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    built_in = await make_sound_effect(None, b"bleep", name="classic")

    assert (await client.get(f"/sound-effects/{built_in.id}/file", headers=user.headers)).content == b"bleep"
    r = await client.delete(f"/sound-effects/{built_in.id}", headers=user.headers)
    assert r.status_code == 404
    assert read_stored(built_in.file_path) == b"bleep"


async def test_other_users_effects_are_invisible(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user, other = await make_user(), await make_user()
    theirs = await make_sound_effect(other.id)

    assert (await client.get(f"/sound-effects/{theirs.id}/file", headers=user.headers)).status_code == 404
    assert (await client.delete(f"/sound-effects/{theirs.id}", headers=user.headers)).status_code == 404
    assert read_stored(theirs.file_path) is not None


async def test_names_are_unique_per_user(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    user, other = await make_user(), await make_user()
    assert (await upload(client, user.headers, name="honk")).status_code == 201

    r = await upload(client, user.headers, name="honk")
    assert r.status_code == 409 and "already have" in r.json()["detail"]
    assert (await upload(client, other.headers, name="honk")).status_code == 201  # others may
    assert len(stored_keys("effects")) == 2  # the refused one wasn't kept


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"filename": "notes.txt"}, 422),
        ({"filename": "no_extension"}, 422),
        ({"name": "   "}, 422),
        ({"name": "x" * 101}, 422),
        ({"content": b"x" * (2 * 1024 * 1024 + 1)}, 413),
    ],
    ids=["not-audio-extension", "no-extension", "blank-name", "long-name", "too-large"],
)
async def test_bad_uploads_are_refused_and_nothing_kept(
    client: httpx.AsyncClient, make_user: MakeUser, kwargs: dict, code: int
) -> None:
    user = await make_user()
    name = kwargs.pop("name", "honk")
    r = await upload(client, user.headers, name=name, **kwargs)
    assert r.status_code == code, r.text
    assert stored_keys("effects") == []


async def test_per_user_limit(
    client: httpx.AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_api_settings(), "MAX_SOUND_EFFECTS_PER_USER", 2)
    user = await make_user()
    for name in ("one", "two"):
        assert (await upload(client, user.headers, name=name)).status_code == 201

    r = await upload(client, user.headers, name="three")
    assert r.status_code == 409 and "already have 2" in r.json()["detail"]


async def test_effect_used_by_a_running_job_cannot_be_deleted(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    effect = await make_sound_effect(user.id)
    running = await make_audio(
        user.id, AudioStatus.PROCESSING, censor_mode=CensorMode.SOUND_EFFECT, sound_effect_id=effect.id
    )

    r = await client.delete(f"/sound-effects/{effect.id}", headers=user.headers)
    assert r.status_code == 409

    # Once the job is done, it can go; the finished job keeps its record.
    from tests.helpers import update_audio_row

    await update_audio_row(running.id, status=AudioStatus.COMPLETED)
    assert (await client.delete(f"/sound-effects/{effect.id}", headers=user.headers)).status_code == 204
    finished = await get_audio_row(running.id)
    assert finished is not None and finished.sound_effect_id is None


async def test_uploaded_effect_can_be_used_for_censoring(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    effect_id = (await upload(client, user.headers)).json()["id"]

    r = await client.post(
        "/censor",
        headers=user.headers,
        files={"file": ("song.mp3", b"song", "audio/mpeg")},
        data={"censor_mode": "sound_effect", "sound_effect_id": effect_id},
    )

    assert r.status_code == 202
    stored = await get_audio_row(UUID(r.json()["id"]))
    assert stored is not None and stored.sound_effect_id == UUID(effect_id)


async def test_requires_login(client: httpx.AsyncClient) -> None:
    assert (await client.get("/sound-effects")).status_code == 401
    assert (await client.delete(f"/sound-effects/{uuid4()}")).status_code == 401
