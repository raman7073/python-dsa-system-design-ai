"""Subtitles (SRT or WebVTT) from a stored transcript, with the flagged words
masked: "fuck," -> "f***," (symbol "*", 1 visible character).

Pure Python (no torch or ffmpeg), so the API can import it.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

# Cue limits, as in common subtitle guidelines: two lines of at most 42
# characters, on screen for at most 6 seconds.
MAX_LINE_CHARS = 42
MAX_LINES = 2
MAX_CUE_SECONDS = 6.0
# A pause this long between words starts a new cue.
PAUSE_SECONDS = 1.0
# A cue is shown at least this long (when the next one leaves room).
MIN_CUE_SECONDS = 0.7
SENTENCE_END = (".", "?", "!")


class SubtitleFormat(StrEnum):
    SRT = "srt"
    VTT = "vtt"

    @property
    def media_type(self) -> str:
        return "application/x-subrip" if self is SubtitleFormat.SRT else "text/vtt"


@dataclass(frozen=True)
class Cue:
    start: float  # seconds
    end: float
    lines: list[str]


def mask_word(word: str, symbol: str = "*", visible_chars: int = 1) -> str:
    """`word` with all but its first `visible_chars` characters replaced by
    `symbol`. Punctuation around it stays ("fuck," -> "f***,"), and at least
    one character is always masked (a short word isn't shown whole)."""
    alnum = [i for i, ch in enumerate(word) if ch.isalnum()]
    if not alnum:  # only symbols ("$#!"): mask all of it
        return symbol * len(word)
    first, last = alnum[0], alnum[-1]
    core = word[first : last + 1]
    visible = min(visible_chars, len(core) - 1)
    masked = core[:visible] + symbol * (len(core) - visible)
    return word[:first] + masked + word[last + 1 :]


def _timings(words: Sequence[dict]) -> list[tuple[float, float]]:
    """Each word's (start, end). The aligner leaves some words untimed
    (numbers, symbols): they get the gap between their timed neighbours."""
    next_start: list[float | None] = [None] * len(words)
    upcoming: float | None = None
    for i in range(len(words) - 1, -1, -1):
        next_start[i] = upcoming
        if words[i].get("start") is not None:
            upcoming = words[i]["start"]

    out: list[tuple[float, float]] = []
    prev_end = 0.0
    for i, w in enumerate(words):
        start: float | None = w.get("start")
        end: float | None = w.get("end")
        if end is None:
            following = next_start[i]
            if following is not None:
                end = following
            else:
                end = start if start is not None else prev_end
        if start is None:
            start = min(prev_end, end)
        end = max(end, start)
        out.append((start, end))
        prev_end = end
    return out


def _wrap(tokens: Sequence[str]) -> list[str]:
    """Greedy line wrapping at MAX_LINE_CHARS (a longer word gets its own line)."""
    lines: list[str] = []
    for token in tokens:
        if lines and len(lines[-1]) + 1 + len(token) <= MAX_LINE_CHARS:
            lines[-1] += " " + token
        else:
            lines.append(token)
    return lines


def build_cues(
    words: Sequence[dict], symbol: str = "*", visible_chars: int = 1
) -> list[Cue]:
    """Group transcript words into cues, masking the flagged ones.

    A new cue starts when the text would need more than MAX_LINES lines, the
    cue would last longer than MAX_CUE_SECONDS, after a pause of
    PAUSE_SECONDS, or after a sentence ends.
    """
    groups: list[tuple[float, float, list[str]]] = []
    tokens: list[str] = []
    start = end = 0.0
    for w, (w_start, w_end) in zip(words, _timings(words), strict=True):
        text = str(w.get("word", "")).strip()
        if not text:
            continue
        if w.get("flagged"):
            text = mask_word(text, symbol, visible_chars)
        if tokens and (
            len(_wrap([*tokens, text])) > MAX_LINES
            or w_end - start > MAX_CUE_SECONDS
            or w_start - end >= PAUSE_SECONDS
            or tokens[-1].endswith(SENTENCE_END)
        ):
            groups.append((start, end, tokens))
            tokens = []
        if not tokens:
            start = w_start
        tokens.append(text)
        end = w_end
    if tokens:
        groups.append((start, end, tokens))

    cues: list[Cue] = []
    for i, (c_start, c_end, c_tokens) in enumerate(groups):
        # Untimed or very short words would flash by: show the cue a little
        # longer, without running into the next one.
        limit = groups[i + 1][0] if i + 1 < len(groups) else None
        if c_end - c_start < MIN_CUE_SECONDS:
            c_end = c_start + MIN_CUE_SECONDS
            if limit is not None:
                c_end = max(min(c_end, limit), c_start)
        cues.append(Cue(c_start, c_end, _wrap(c_tokens)))
    return cues


def _timestamp(seconds: float, sep: str) -> str:
    ms = round(max(seconds, 0.0) * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _escape_vtt(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(cues: Iterable[Cue], fmt: SubtitleFormat) -> str:
    """The cues as an SRT or WebVTT document."""
    blocks: list[str] = []
    for n, cue in enumerate(cues, start=1):
        if fmt is SubtitleFormat.SRT:
            times = f"{_timestamp(cue.start, ',')} --> {_timestamp(cue.end, ',')}"
            blocks.append(f"{n}\n{times}\n" + "\n".join(cue.lines))
        else:
            times = f"{_timestamp(cue.start, '.')} --> {_timestamp(cue.end, '.')}"
            blocks.append(
                f"{times}\n" + "\n".join(_escape_vtt(line) for line in cue.lines)
            )
    body = "\n\n".join(blocks)
    if fmt is SubtitleFormat.VTT:
        return "WEBVTT\n\n" + body + ("\n" if body else "")
    return body + ("\n" if body else "")


def subtitles(
    words: Sequence[dict],
    fmt: SubtitleFormat = SubtitleFormat.SRT,
    symbol: str = "*",
    visible_chars: int = 1,
) -> str:
    """The transcript as subtitles, flagged words masked."""
    return render(build_cues(words, symbol, visible_chars), fmt)
