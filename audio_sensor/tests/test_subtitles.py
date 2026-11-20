"""Subtitles with masked profanity: app.subtitles, and GET /audio/{id}/subtitles."""

import httpx
import pytest

from app.database.models import AudioStatus, JobStage
from app.subtitles import (
    MAX_CUE_SECONDS,
    MAX_LINE_CHARS,
    SubtitleFormat,
    build_cues,
    mask_word,
    subtitles,
)
from tests.helpers import MakeUser, make_audio, make_transcript


def w(word: str, start: float | None, end: float | None, flagged: bool = False) -> dict:
    out: dict = {"word": word, "flagged": flagged}
    if start is not None:
        out["start"] = start
    if end is not None:
        out["end"] = end
    return out


# --- Masking -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "symbol", "visible", "expected"),
    [
        ("fuck", "*", 1, "f***"),
        ("fuck,", "*", 1, "f***,"),  # punctuation stays
        ('"Shit!"', "#", 1, '"S***!"'.replace("*", "#")),
        ("fuck", "*", 0, "****"),
        ("fuck", "*", 2, "fu**"),
        ("ass", "*", 10, "as*"),  # never shown whole
        ("a", "*", 1, "*"),
        ("$#!", "*", 1, "***"),  # nothing alphanumeric: all masked
        ("motherf'er", "-", 1, "m---------"),
        ("scheiße", "*", 1, "s******"),
    ],
)
def test_mask_word(word: str, symbol: str, visible: int, expected: str) -> None:
    assert mask_word(word, symbol, visible) == expected


# --- Cues ----------------------------------------------------------------------------------


def test_only_flagged_words_are_masked_srt() -> None:
    words = [w("what", 0.0, 0.3), w("the", 0.3, 0.5), w("fuck", 0.5, 0.9, flagged=True)]

    assert subtitles(words) == "1\n00:00:00,000 --> 00:00:00,900\nwhat the f***\n"


def test_vtt_has_header_dot_millis_and_escapes_markup() -> None:
    words = [w("Tom", 1.0, 1.4), w("&", 1.4, 1.5), w("<Jerry>", 1.5, 2.25)]

    out = subtitles(words, SubtitleFormat.VTT)

    assert out == "WEBVTT\n\n00:00:01.000 --> 00:00:02.250\nTom &amp; &lt;Jerry&gt;\n"


def test_cues_split_on_sentences_pauses_and_length() -> None:
    words = [
        w("Hello.", 0.0, 0.5),
        w("How", 0.6, 0.8),  # new sentence
        w("are", 0.8, 1.0),
        w("you", 3.0, 3.3),  # after a 2 s pause
    ]
    cues = build_cues(words)
    assert [c.lines for c in cues] == [["Hello."], ["How are"], ["you"]]

    long_talk = [w(f"word{i}", i * 0.2, i * 0.2 + 0.2) for i in range(60)]
    cues = build_cues(long_talk)
    assert len(cues) > 1
    for cue in cues:
        assert len(cue.lines) <= 2
        assert all(len(line) <= MAX_LINE_CHARS for line in cue.lines)
        assert cue.end - cue.start <= MAX_CUE_SECONDS
    assert " ".join(" ".join(c.lines) for c in cues) == " ".join(
        x["word"] for x in long_talk
    )


def test_untimed_words_take_their_neighbours_gap() -> None:
    # The aligner can't place numbers: "1984" sits between 0.4 and 1.0.
    cues = build_cues([w("in", 0.0, 0.4), w("1984", None, None), w("we", 1.0, 1.2)])

    assert len(cues) == 1 and (cues[0].start, cues[0].end) == (0.0, 1.2)
    assert cues[0].lines == ["in 1984 we"]


def test_short_cues_are_stretched_without_overlapping() -> None:
    cues = build_cues([w("Hi.", 0.0, 0.1), w("Yo.", 0.3, 0.4)])

    assert (cues[0].start, cues[0].end) == (0.0, 0.3)  # up to the next cue
    assert cues[1].end == pytest.approx(1.0)  # 0.3 + MIN_CUE_SECONDS


def test_no_words_gives_an_empty_file() -> None:
    assert subtitles([]) == ""
    assert subtitles([], SubtitleFormat.VTT) == "WEBVTT\n\n"


# --- The endpoint --------------------------------------------------------------------------

WORDS = [
    {"word": "you", "start": 0.0, "end": 0.3, "score": 0.9, "flagged": False},
    {"word": "shit,", "start": 0.3, "end": 0.7, "score": 0.8, "flagged": True},
    {"word": "man", "start": 0.7, "end": 1.0, "score": 0.9, "flagged": False},
]


async def detected_audio(user_id, stage: JobStage = JobStage.RENDERED, words=WORDS):
    status = (
        AudioStatus.COMPLETED if stage == JobStage.RENDERED else AudioStatus.PROCESSING
    )
    record = await make_audio(user_id, status, stage=stage)
    await make_transcript(record.id, words)
    return record


async def test_download_srt_with_defaults(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await detected_audio(user.id)

    r = await client.get(f"/audio/{record.id}/subtitles", headers=user.headers)

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-subrip; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="{record.id}.srt"'
    assert r.text == "1\n00:00:00,000 --> 00:00:01,000\nyou s***, man\n"


async def test_download_vtt_with_options(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await detected_audio(user.id)

    r = await client.get(
        f"/audio/{record.id}/subtitles",
        headers=user.headers,
        params={"format": "vtt", "symbol": "#", "visible_chars": 0},
    )

    assert r.status_code == 200
    assert r.headers["content-type"] == "text/vtt; charset=utf-8"
    assert r.headers["content-disposition"].endswith(f'filename="{record.id}.vtt"')
    assert r.text == "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nyou ####, man\n"


async def test_available_once_detected_before_rendering(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await detected_audio(user.id, JobStage.DETECTED)

    r = await client.get(f"/audio/{record.id}/subtitles", headers=user.headers)

    assert r.status_code == 200 and "s***," in r.text


async def test_head_returns_headers_only(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user = await make_user()
    record = await detected_audio(user.id)

    r = await client.head(f"/audio/{record.id}/subtitles", headers=user.headers)

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/x-subrip")


@pytest.mark.parametrize(
    "params",
    [
        {"symbol": "ab"},
        {"symbol": ""},
        {"symbol": "x"},
        {"symbol": "7"},
        {"symbol": " "},
        {"symbol": "<"},
        {"visible_chars": -1},
        {"visible_chars": 11},
        {"format": "ass"},
    ],
    ids=[
        "two-chars",
        "empty",
        "letter",
        "digit",
        "space",
        "markup",
        "negative",
        "too-many",
        "unknown-format",
    ],
)
async def test_bad_options_are_refused(
    client: httpx.AsyncClient, make_user: MakeUser, params: dict
) -> None:
    user = await make_user()
    record = await detected_audio(user.id)

    r = await client.get(
        f"/audio/{record.id}/subtitles", headers=user.headers, params=params
    )

    assert r.status_code == 422, r.text


@pytest.mark.parametrize(
    ("status", "message"),
    [(AudioStatus.PROCESSING, "try again shortly"), (AudioStatus.FAILED, "re-run it")],
)
async def test_not_available_before_detection(
    client: httpx.AsyncClient, make_user: MakeUser, status: AudioStatus, message: str
) -> None:
    # Also the case while a PATCH with new custom words waits to re-detect:
    # the old flags no longer apply.
    user = await make_user()
    record = await make_audio(user.id, status, stage=JobStage.TRANSCRIBED)
    await make_transcript(record.id, [{"word": "hello", "start": 0.0, "end": 0.4}])

    r = await client.get(f"/audio/{record.id}/subtitles", headers=user.headers)

    assert r.status_code == 409 and message in r.json()["detail"]


@pytest.mark.parametrize(
    ("status", "code"), [(AudioStatus.PENDING, 409), (AudioStatus.FAILED, 404)]
)
async def test_no_transcript(
    client: httpx.AsyncClient, make_user: MakeUser, status: AudioStatus, code: int
) -> None:
    user = await make_user()
    record = await make_audio(user.id, status)

    r = await client.get(f"/audio/{record.id}/subtitles", headers=user.headers)

    assert r.status_code == code


async def test_other_users_subtitles_are_not_found(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    owner, other = await make_user(), await make_user()
    record = await detected_audio(owner.id)

    r = await client.get(f"/audio/{record.id}/subtitles", headers=other.headers)

    assert r.status_code == 404 and "man" not in r.text


async def test_requires_login(client: httpx.AsyncClient, make_user: MakeUser) -> None:
    record = await detected_audio((await make_user()).id)
    assert (await client.get(f"/audio/{record.id}/subtitles")).status_code == 401
