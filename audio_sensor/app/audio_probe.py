"""Read an audio file's duration from its headers, in pure Python (mutagen).

The API has no ffmpeg (its image stays small), so this is how it checks
uploads before storing them: that a sound effect is really audio and short,
and that an upload isn't obviously longer than allowed. Headers can lie, so
the worker enforces the limits again when it decodes (app.audio_censor).
"""

from typing import BinaryIO

from mutagen import File as read_audio_file
from mutagen import MutagenError
from mutagen.aac import AAC
from mutagen.wave import WAVE

# mutagen.File() doesn't recognize these on its own; their readers do.
_READERS = {".wav": WAVE, ".aac": AAC}


def header_duration(source: BinaryIO, suffix: str) -> float | None:
    """The duration in seconds the file's headers declare, or None if they
    can't be read as audio (not audio at all, or a format mutagen doesn't
    know, such as WebM). The read position is put back afterwards."""
    position = source.tell()
    try:
        reader = _READERS.get(suffix.lower())
        audio = reader(source) if reader else read_audio_file(source)
        length = audio.info.length if audio is not None else None
    except (MutagenError, AttributeError, ValueError, OSError, EOFError):
        length = None
    finally:
        source.seek(position)
    return float(length) if length and length > 0 else None
