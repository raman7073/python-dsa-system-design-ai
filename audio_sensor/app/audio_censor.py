import logging
import math
import shutil
import subprocess
import warnings
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import NotRequired, TypedDict, cast

import numpy as np
import torch
import whisperx
from better_profanity import Profanity
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
from pydub.generators import Sine

from app.censor_words import (  # noqa: F401 (re-exported)
    MAX_CUSTOM_WORD_LENGTH,
    MAX_CUSTOM_WORDS,
    InvalidCustomWordsError,
    normalize_custom_words,
)

logger = logging.getLogger(__name__)

# pyannote (used by WhisperX for voice-activity detection) warns that torchcodec
# can't load. Harmless: WhisperX hands it audio already decoded in memory.
warnings.filterwarnings("ignore", message=r"\s*torchcodec is not installed correctly")


class Word(TypedDict):
    word: str
    # Times in seconds. Missing when the aligner couldn't place the word
    # (this can happen with numbers or symbols).
    start: NotRequired[float]
    end: NotRequired[float]
    score: NotRequired[float]
    flagged: NotRequired[bool]  # set by detect_profanity()


class AudioDecodeError(ValueError):
    """The input file could not be decoded as audio."""


class AudioTooLongError(ValueError):
    """The audio is longer than allowed (max_seconds)."""

    def __init__(self, max_seconds: float):
        self.max_seconds = max_seconds
        super().__init__(f"The audio is longer than {max_seconds / 60:.0f} minutes")


SAMPLE_RATE = 16000  # what Whisper expects

# What ffprobe calls each output format, to tell whether a file's content
# matches its extension.
_FORMAT_NAMES = {".mp3": {"mp3"}, ".wav": {"wav"}, ".flac": {"flac"}, ".ogg": {"ogg"}}


def _load_audio(path: str, max_seconds: float | None) -> np.ndarray:
    """Decode any format ffmpeg understands to 16 kHz mono float32, as
    whisperx.load_audio does, but reading at most `max_seconds` (+1): a small
    file can hold hours of audio, and decoding all of it would take gigabytes
    of memory before its length could even be checked."""
    limit = ["-t", str(max_seconds + 1)] if max_seconds else []
    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0", "-i", path, *limit,
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-",
    ]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        raise AudioDecodeError(f"Could not decode {path!r} as audio") from exc
    return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0


def _format_matches(path: str, suffix: str) -> bool:
    """Whether the file really is the format its extension says (e.g. WAV
    data named .mp3 isn't). Unknown suffixes, or ffprobe failing, count as a
    match, so the file is kept as it is."""
    expected = _FORMAT_NAMES.get(suffix.lower())
    if expected is None:
        return True
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name",
             "-of", "default=nw=1:nk=1", path],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        logger.warning("Couldn't check the format of %r; keeping it as it is", path)
        return True
    return bool(expected & set(out.strip().split(",")))


class SoundEffectError(ValueError):
    """The sound effect file could not be decoded as audio (or is empty)."""




class AudioCensor:
    """Transcribes audio, flags profanity, and replaces it with silence, a
    beep, or a sound effect.

    Words flagged: better_profanity's built-in list, plus `censor_words` (for
    every file this instance handles), plus any `custom_words` passed for one
    file. One instance serves many users' files in turn, so per-file words
    never change the shared list.

    Not thread-safe: use one instance per process (the Celery worker runs one
    job at a time per process). Models load on first use and are kept, since
    loading takes far longer than a typical job.
    """

    DEVICE = "cpu"
    LANGUAGE = "en"
    # The classic broadcast "bleep": a 1 kHz sine tone.
    BEEP_FREQUENCY_HZ = 1000
    BEEP_VOLUME_DBFS = -20.0
    # Short fade at each end of a beep or sound effect so it doesn't click
    # on/off.
    BEEP_FADE_MS = 5
    # Word lists for recently seen sets of custom words (users often reuse
    # theirs). Building one takes a few milliseconds.
    PROFANITY_CACHE_SIZE = 32

    def __init__(
        self,
        censor_words: list[str] | None = None,
        model_name: str = "small",
        compute_type: str = "int8",
        batch_size: int = 8,
        vad_onset: float = 0.3,
        vad_offset: float = 0.2,
        threads: int | None = None,
        max_effect_seconds: float = 10,
    ):
        self.censor_words = censor_words or []
        self.model_name = model_name
        # int8 is the fastest compute type on CPU; float16 is GPU-only.
        self.compute_type = compute_type
        self.batch_size = batch_size
        # Voice-activity detection thresholds. WhisperX's defaults (0.5/0.363)
        # can skip short or shouted words entirely, e.g. a lone "f***!"; for a
        # censor, missing a word is worse than transcribing a bit of noise.
        self.vad_options = {"vad_onset": vad_onset, "vad_offset": vad_offset}
        # CPU threads for transcription. WhisperX's default is 4; by default
        # use one per physical core (what torch picks), since a worker runs
        # one job at a time.
        self.threads = threads or torch.get_num_threads()
        # Sound effects are never decoded beyond this (a small file can hold
        # hours); they are repeated or cut to fit each word anyway.
        self.max_effect_seconds = max_effect_seconds

        # better_profanity's built-in English word list plus our own censor
        # words. A per-instance Profanity (instead of the module-level
        # `profanity` singleton) keeps each AudioCensor's word list separate.
        self._profanity = Profanity()
        if self.censor_words:
            self._profanity.add_censor_words(self.censor_words)
        # The same plus a file's custom words, keyed by those words.
        self._custom_profanity: OrderedDict[frozenset[str], Profanity] = OrderedDict()

        # Loaded on first use and kept. The alignment model (word timestamps)
        # is only needed to mute something, so a worker that only ever sees
        # clean audio never loads it.
        self._asr_model = None
        self._align_model = None
        self._align_metadata = None

    def load_models(self) -> None:
        """Load both models now instead of on first use."""
        self._get_asr_model()
        self._get_align_model()

    def _get_asr_model(self):
        if self._asr_model is None:
            logger.info("Loading Whisper model %r (%d threads)", self.model_name, self.threads)
            self._asr_model = whisperx.load_model(
                self.model_name,
                self.DEVICE,
                compute_type=self.compute_type,
                language=self.LANGUAGE,
                vad_options=self.vad_options,
                threads=self.threads,
            )
        return self._asr_model

    def _get_align_model(self):
        if self._align_model is None:
            logger.info("Loading alignment model")
            self._align_model, self._align_metadata = whisperx.load_align_model(
                language_code=self.LANGUAGE,
                device=self.DEVICE,
            )
        return self._align_model, self._align_metadata

    def censor_audio(
        self,
        audio_path: str,
        output_path: str | None = None,
        padding_ms: int = 150,
        beep: bool = False,
        copy_unchanged: bool = True,
        custom_words: Sequence[str] | None = None,
        sound_effect_path: str | None = None,
        max_seconds: float | None = None,
    ) -> tuple[str | None, list[Word]]:
        """Full pipeline: transcribe, flag profanity, then replace it.

        Each flagged word is replaced by silence, by a beep (`beep=True`), or
        by the sound in `sound_effect_path` (looped or cut to fit). Besides
        the built-in list, `custom_words` are censored in this file only
        (validated by normalize_custom_words()).

        Returns (output_path, words), where `words` is every transcribed word
        with its "flagged" value. If nothing is flagged the audio is still
        written to `output_path` unchanged, so callers always get a file back
        -- unless `copy_unchanged` is False: then, if the output would be an
        exact copy (same format), nothing is written and None is returned in
        place of the path, so the caller can reuse the original file.

        Raises AudioDecodeError if the file isn't decodable audio,
        AudioTooLongError if it is longer than `max_seconds`,
        SoundEffectError if the sound effect isn't, InvalidCustomWordsError
        for a bad custom word list, and ValueError for both `beep` and a
        sound effect.

        Word timestamps (the alignment step) are only needed to mute
        something, so a clean transcript skips alignment and re-encoding, and
        never decodes the sound effect.
        """
        if beep and sound_effect_path:
            raise ValueError("Use either beep or a sound effect, not both")
        profanity = self._profanity_for(custom_words)

        audio = self._decode(audio_path, max_seconds)
        segments = self._transcribe(audio)
        if not any(profanity.contains_profanity(s["text"]) for s in segments):
            # The whole-segment check is at least as strict as the per-word
            # one (it also catches multi-word censor phrases), so nothing
            # would have been flagged.
            words = [
                Word(word=w, flagged=False) for s in segments for w in s["text"].split()
            ]
        else:
            words = self.detect_profanity(self._align(segments, audio), custom_words)
        out = self.render_audio(
            audio_path,
            words,
            output_path,
            padding_ms=padding_ms,
            beep=beep,
            sound_effect_path=sound_effect_path,
            copy_unchanged=copy_unchanged,
        )
        return out, words

    def render_audio(
        self,
        audio_path: str,
        words: list[Word],
        output_path: str | None = None,
        padding_ms: int = 150,
        beep: bool = False,
        sound_effect_path: str | None = None,
        copy_unchanged: bool = True,
    ) -> str | None:
        """Write the censored audio for words already transcribed and flagged
        (transcribe_audio, then detect_profanity).

        Flagged words are replaced as in mute_audio(). With nothing flagged
        the output is the input unchanged: copied (or converted, for another
        format) -- or, if `copy_unchanged` is False and the format is the
        same, not written at all, returning None so the caller can reuse the
        original. Needs no models.
        """
        if not any(w.get("flagged") for w in words):
            out = self._output_path(audio_path, output_path)
            same = out.suffix.lower() == Path(audio_path).suffix.lower()
            if not copy_unchanged and same and _format_matches(audio_path, out.suffix):
                return None
            return self._write_unchanged(audio_path, str(out))
        return self.mute_audio(
            audio_path, words, output_path, padding_ms, beep, sound_effect_path
        )

    def _profanity_for(self, custom_words: Sequence[str] | None) -> Profanity:
        """The word list for one file: the shared one, or the shared one plus
        that file's custom words (built once per set of words, then cached)."""
        words = normalize_custom_words(custom_words or ())
        if not words:
            return self._profanity
        key = frozenset(words)
        cached = self._custom_profanity.get(key)
        if cached is not None:
            self._custom_profanity.move_to_end(key)
            return cached
        profanity = Profanity()
        profanity.add_censor_words([*self.censor_words, *words])
        self._custom_profanity[key] = profanity
        if len(self._custom_profanity) > self.PROFANITY_CACHE_SIZE:
            self._custom_profanity.popitem(last=False)  # least recently used
        return profanity

    def transcribe_audio(self, audio_path: str, max_seconds: float | None = None) -> list[Word]:
        """Transcribe English audio and force-align it for word-level timestamps.

        Returns one Word per transcribed word, in order (without "flagged").
        Raises AudioDecodeError if the file isn't decodable audio, and
        AudioTooLongError if it is longer than `max_seconds`.
        """
        audio = self._decode(audio_path, max_seconds)
        return self._align(self._transcribe(audio), audio)

    @staticmethod
    def _decode(audio_path: str, max_seconds: float | None = None) -> np.ndarray:
        """Any format ffmpeg understands, as 16 kHz mono float32 (for Whisper),
        never decoding more than max_seconds (+1, to tell it was longer)."""
        audio = _load_audio(audio_path, max_seconds)
        if max_seconds and len(audio) > max_seconds * SAMPLE_RATE:
            raise AudioTooLongError(max_seconds)
        return audio

    def _transcribe(self, audio) -> list[dict]:
        """Whisper segments: {"text", "start", "end"} (no word timestamps)."""
        result = self._get_asr_model().transcribe(
            audio, batch_size=self.batch_size, language=self.LANGUAGE
        )
        return list(result["segments"])

    def _align(self, segments: list[dict], audio) -> list[Word]:
        """Force-align segments to get each word's start/end times."""
        align_model, metadata = self._get_align_model()
        aligned = whisperx.align(
            segments,  # type: ignore[arg-type]
            align_model,
            metadata,
            audio,
            self.DEVICE,
            return_char_alignments=False,
        )
        # The aligner returns numpy floats; convert them to plain Python floats
        # so the result is JSON-serializable (e.g. returned from FastAPI).
        words: list[Word] = []
        for segment in aligned["word_segments"]:
            word = Word(word=segment["word"])
            for key in ("start", "end", "score"):
                if key in segment:
                    word[key] = float(segment[key])
            words.append(word)
        return words

    @staticmethod
    def _output_path(audio_path: str, output_path: str | None) -> Path:
        """`output_path`, or "<name>_censored<ext>" next to the input."""
        src = Path(audio_path)
        return Path(output_path) if output_path else src.with_name(
            f"{src.stem}_censored{src.suffix}"
        )

    def _write_unchanged(self, audio_path: str, output_path: str | None) -> str:
        """The input as the output: copied byte for byte when it really is the
        output's format (faster, and no re-encoding loss), else converted --
        including content whose extension lies (WAV data named .mp3), so the
        output's bytes always match its extension."""
        src = Path(audio_path)
        out = self._output_path(audio_path, output_path)
        if out.suffix.lower() == src.suffix.lower() and _format_matches(audio_path, src.suffix):
            shutil.copyfile(src, out)
            return str(out)
        try:
            audio = AudioSegment.from_file(audio_path)
        except CouldntDecodeError as exc:
            raise AudioDecodeError(f"Could not decode {audio_path!r} as audio") from exc
        audio.export(out, format=out.suffix.lstrip(".").lower() or "wav")
        return str(out)

    def detect_profanity(
        self, words: list[Word], custom_words: Sequence[str] | None = None
    ) -> list[Word]:
        """Set "flagged" on each word: True if it is profane or in the censor list.

        Checks better_profanity's default word list plus `censor_words`, plus
        `custom_words` if given. Whole words only ("banana" doesn't flag
        "bananas"). Punctuation attached by the transcriber (e.g. "word.") is
        ignored, and common obfuscations like "sh1t" are also caught. Updates
        the dicts in place and returns the same list.
        """
        profanity = self._profanity_for(custom_words)
        for word in words:
            word["flagged"] = profanity.contains_profanity(word["word"])
        return words

    def mute_audio(
        self,
        audio_path: str,
        words: list[Word],
        output_path: str | None = None,
        padding_ms: int = 150,
        beep: bool = False,
        sound_effect_path: str | None = None,
    ) -> str:
        """Silence (or beep over) every flagged word in the audio and save it.

        Each flagged word is replaced from `start` to `end`, widened by
        `padding_ms` on both sides: alignment timestamps aren't sample-exact,
        and the aligner often ends a word early, especially a shouted word
        ending in a hard consonant. With `beep=True` the span is replaced by
        a 1 kHz tone instead of silence; with `sound_effect_path`, by that
        sound, looped or cut to fit each span.

        `output_path` defaults to "<name>_censored<ext>" next to the input; the
        output format follows its extension (e.g. .wav, .mp3).
        Returns the output path.
        """
        if beep and sound_effect_path:
            raise ValueError("Use either beep or a sound effect, not both")
        try:
            audio = AudioSegment.from_file(audio_path)
        except CouldntDecodeError as exc:
            raise AudioDecodeError(f"Could not decode {audio_path!r} as audio") from exc
        effect = self._load_effect(sound_effect_path, audio) if sound_effect_path else None

        # Rebuild the audio from the clean parts with the filler in between.
        censored = AudioSegment.empty()
        cursor = 0
        for start_ms, end_ms in self._flagged_spans(words, padding_ms, len(audio)):
            censored += audio[cursor:start_ms] + self._make_filler(
                audio, end_ms - start_ms, beep, effect
            )
            cursor = end_ms
        censored += audio[cursor:]

        out = self._output_path(audio_path, output_path)
        censored.export(out, format=out.suffix.lstrip(".").lower() or "wav")
        return str(out)

    @staticmethod
    def _flagged_spans(
        words: list[Word], padding_ms: int, audio_len_ms: int
    ) -> list[tuple[int, int]]:
        """Padded (start_ms, end_ms) spans of flagged words, sorted and merged.

        A flagged word the aligner couldn't place (no timestamps: numbers or
        symbols, e.g. a custom word "1984") is never skipped: its span is
        estimated from the words around it (see _estimated_bounds).
        """
        spans = []
        for i, word in enumerate(words):
            if not word.get("flagged"):
                continue
            if "start" in word and "end" in word:
                start_ms, end_ms = int(word["start"] * 1000), int(word["end"] * 1000)
            else:
                start_ms, end_ms = AudioCensor._estimated_bounds(words, i, audio_len_ms)
                logger.warning(
                    "%r has no timestamps; censoring %d-%d ms around it",
                    word["word"], start_ms, end_ms,
                )  # fmt: skip
            spans.append((
                max(0, start_ms - padding_ms),
                min(audio_len_ms, end_ms + padding_ms),
            ))

        merged: list[tuple[int, int]] = []
        for start_ms, end_ms in sorted(spans):
            if merged and start_ms <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))
            else:
                merged.append((start_ms, end_ms))
        return merged

    # Shorter than this, the gap between a word's neighbours can't hold it:
    # the aligner gave the neighbours its time.
    MIN_ESTIMATED_MS = 250

    @staticmethod
    def _estimated_bounds(words: list[Word], i: int, audio_len_ms: int) -> tuple[int, int]:
        """Where a word without timestamps must be: between the nearest timed
        words before and after it (the start or end of the audio if there are
        none). If that gap is too short, the neighbours are included too.
        Censoring a little too much beats letting a flagged word through."""

        def timed(j: int) -> bool:
            return "start" in words[j] and "end" in words[j]

        before = next((words[j] for j in range(i - 1, -1, -1) if timed(j)), None)
        after = next((words[j] for j in range(i + 1, len(words)) if timed(j)), None)
        # (timed() guarantees the keys; .get() only satisfies the type checker.)
        start = int(before.get("end", 0) * 1000) if before else 0
        end = int(after.get("start", 0) * 1000) if after else audio_len_ms
        if end - start < AudioCensor.MIN_ESTIMATED_MS:
            start = int(before.get("start", 0) * 1000) if before else 0
            end = int(after.get("end", 0) * 1000) if after else audio_len_ms
        return start, end

    def _load_effect(self, path: str, audio: AudioSegment) -> AudioSegment:
        """The sound effect (at most max_effect_seconds of it), converted once
        to `audio`'s format (frame rate, channels, sample width) so every span
        joins without resampling."""
        try:
            effect = AudioSegment.from_file(path, duration=self.max_effect_seconds)
        except CouldntDecodeError as exc:
            raise SoundEffectError(f"Could not decode sound effect {path!r}") from exc
        if len(effect) == 0:
            raise SoundEffectError(f"Sound effect {path!r} is empty")
        return (
            effect.set_frame_rate(audio.frame_rate)
            .set_channels(audio.channels)
            .set_sample_width(audio.sample_width)
        )

    def _make_filler(
        self,
        audio: AudioSegment,
        duration_ms: int,
        beep: bool,
        effect: AudioSegment | None = None,
    ) -> AudioSegment:
        """Silence, a beep, or the sound effect, `duration_ms` long, matching
        `audio`'s format.

        Same frame rate, channels and sample width as the source, so the
        pieces join without resampling. A sound effect shorter than the span
        is repeated, a longer one cut, and it fades in and out like the beep.
        """
        if effect is not None:
            repeats = math.ceil(duration_ms / len(effect))
            # cast: pydub's stubs type slicing as a generator.
            filler = cast(AudioSegment, (effect * repeats)[:duration_ms])
            fade = min(self.BEEP_FADE_MS, duration_ms // 2)
            return filler.fade_in(fade).fade_out(fade)
        if beep:
            filler = Sine(
                self.BEEP_FREQUENCY_HZ,
                sample_rate=audio.frame_rate,
                bit_depth=audio.sample_width * 8,
            ).to_audio_segment(duration=duration_ms, volume=self.BEEP_VOLUME_DBFS)
            fade = min(self.BEEP_FADE_MS, duration_ms // 2)
            filler = filler.fade_in(fade).fade_out(fade)
        else:
            filler = AudioSegment.silent(duration=duration_ms, frame_rate=audio.frame_rate)
        return filler.set_channels(audio.channels).set_sample_width(audio.sample_width)


# Usage example (runs only when this file is executed directly, not on import).
if __name__ == "__main__":
    audio_path = r"C:\Users\Lenovo\Downloads\freesound_community-fuck-36089.mp3"
    censor = AudioCensor(censor_words=["badword1", "badword2"])
    out_path, words = censor.censor_audio(audio_path, beep=True)

    print(f"{'START':>7}  {'END':>7}  {'SCORE':>5}  {'FLAGGED':<7}  WORD")
    for w in words:
        start = f"{w['start']:.3f}" if "start" in w else "-"
        end = f"{w['end']:.3f}" if "end" in w else "-"
        score = f"{w['score']:.2f}" if "score" in w else "-"
        flagged = "YES" if w.get("flagged") else "no"
        print(f"{start:>7}  {end:>7}  {score:>5}  {flagged:<7}  {w['word']}")

    flagged_count = sum(1 for w in words if w.get("flagged"))
    print(f"\n{len(words)} words, {flagged_count} flagged")
    print(f"Censored audio saved to: {out_path}")
