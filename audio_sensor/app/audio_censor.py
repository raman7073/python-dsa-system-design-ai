import logging
import shutil
import warnings
from pathlib import Path
from typing import NotRequired, TypedDict

import torch
import whisperx
from better_profanity import Profanity
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
from pydub.generators import Sine

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


class AudioCensor:
    """Transcribes audio, flags profanity, and mutes or beeps it out.

    Not thread-safe: use one instance per process (the Celery worker runs one
    job at a time per process). Models load on first use and are kept, since
    loading takes far longer than a typical job.
    """

    DEVICE = "cpu"
    LANGUAGE = "en"
    # The classic broadcast "bleep": a 1 kHz sine tone.
    BEEP_FREQUENCY_HZ = 1000
    BEEP_VOLUME_DBFS = -20.0
    # Short fade at each end of a beep so it doesn't click on/off.
    BEEP_FADE_MS = 5

    def __init__(
        self,
        censor_words: list[str] | None = None,
        model_name: str = "small",
        compute_type: str = "int8",
        batch_size: int = 8,
        vad_onset: float = 0.3,
        vad_offset: float = 0.2,
        threads: int | None = None,
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

        # better_profanity's built-in English word list plus our own censor
        # words. A per-instance Profanity (instead of the module-level
        # `profanity` singleton) keeps each AudioCensor's word list separate.
        self._profanity = Profanity()
        if self.censor_words:
            self._profanity.add_censor_words(self.censor_words)

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
    ) -> tuple[str | None, list[Word]]:
        """Full pipeline: transcribe, flag profanity, then mute or beep it.

        Returns (output_path, words), where `words` is every transcribed word
        with its "flagged" value. If nothing is flagged the audio is still
        written to `output_path` unchanged, so callers always get a file back
        -- unless `copy_unchanged` is False: then, if the output would be an
        exact copy (same format), nothing is written and None is returned in
        place of the path, so the caller can reuse the original file.
        Raises AudioDecodeError if the file isn't decodable audio.

        Word timestamps (the alignment step) are only needed to mute
        something, so a clean transcript skips alignment and re-encoding.
        """
        audio = self._decode(audio_path)
        segments = self._transcribe(audio)
        if not any(self._profanity.contains_profanity(s["text"]) for s in segments):
            # The whole-segment check is at least as strict as the per-word
            # one (it also catches multi-word censor phrases), so nothing
            # would have been flagged.
            words = [
                Word(word=w, flagged=False) for s in segments for w in s["text"].split()
            ]
            out = self._output_path(audio_path, output_path)
            if not copy_unchanged and out.suffix.lower() == Path(audio_path).suffix.lower():
                return None, words
            return self._write_unchanged(audio_path, str(out)), words

        words = self.detect_profanity(self._align(segments, audio))
        out = self.mute_audio(audio_path, words, output_path, padding_ms, beep)
        return out, words

    def transcribe_audio(self, audio_path: str) -> list[Word]:
        """Transcribe English audio and force-align it for word-level timestamps.

        Returns one Word per transcribed word, in order (without "flagged").
        Raises AudioDecodeError if the file isn't decodable audio.
        """
        audio = self._decode(audio_path)
        return self._align(self._transcribe(audio), audio)

    @staticmethod
    def _decode(audio_path: str):
        """Any format ffmpeg understands, as 16 kHz mono float32 (for Whisper)."""
        try:
            return whisperx.load_audio(audio_path)
        except RuntimeError as exc:
            raise AudioDecodeError(f"Could not decode {audio_path!r} as audio") from exc

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
        """The input as the output: copied byte for byte when the format is
        the same (faster, and no re-encoding loss), else converted."""
        src = Path(audio_path)
        out = self._output_path(audio_path, output_path)
        if out.suffix.lower() == src.suffix.lower():
            shutil.copyfile(src, out)
            return str(out)
        try:
            audio = AudioSegment.from_file(audio_path)
        except CouldntDecodeError as exc:
            raise AudioDecodeError(f"Could not decode {audio_path!r} as audio") from exc
        audio.export(out, format=out.suffix.lstrip(".").lower() or "wav")
        return str(out)

    def detect_profanity(self, words: list[Word]) -> list[Word]:
        """Set "flagged" on each word: True if it is profane or in the censor list.

        Checks better_profanity's default word list plus `censor_words`.
        Punctuation attached by the transcriber (e.g. "word.") is ignored, and
        common obfuscations like "sh1t" are also caught. Updates the dicts in
        place and returns the same list.
        """
        for word in words:
            word["flagged"] = self._profanity.contains_profanity(word["word"])
        return words

    def mute_audio(
        self,
        audio_path: str,
        words: list[Word],
        output_path: str | None = None,
        padding_ms: int = 150,
        beep: bool = False,
    ) -> str:
        """Silence (or beep over) every flagged word in the audio and save it.

        Each flagged word is replaced from `start` to `end`, widened by
        `padding_ms` on both sides: alignment timestamps aren't sample-exact,
        and the aligner often ends a word early, especially a shouted word
        ending in a hard consonant. With `beep=True` the span is replaced by
        a 1 kHz tone instead of silence.

        `output_path` defaults to "<name>_censored<ext>" next to the input; the
        output format follows its extension (e.g. .wav, .mp3).
        Returns the output path.
        """
        try:
            audio = AudioSegment.from_file(audio_path)
        except CouldntDecodeError as exc:
            raise AudioDecodeError(f"Could not decode {audio_path!r} as audio") from exc

        # Rebuild the audio from the clean parts with silence/beeps in between.
        censored = AudioSegment.empty()
        cursor = 0
        for start_ms, end_ms in self._flagged_spans(words, padding_ms, len(audio)):
            censored += audio[cursor:start_ms] + self._make_filler(
                audio, end_ms - start_ms, beep
            )
            cursor = end_ms
        censored += audio[cursor:]

        src = Path(audio_path)
        out = Path(output_path) if output_path else src.with_name(
            f"{src.stem}_censored{src.suffix}"
        )
        censored.export(out, format=out.suffix.lstrip(".").lower() or "wav")
        return str(out)

    @staticmethod
    def _flagged_spans(
        words: list[Word], padding_ms: int, audio_len_ms: int
    ) -> list[tuple[int, int]]:
        """Padded (start_ms, end_ms) spans of flagged words, sorted and merged.

        Flagged words without timestamps can't be located, so they are
        skipped with a warning.
        """
        spans = []
        for word in words:
            if not word.get("flagged"):
                continue
            if "start" not in word or "end" not in word:
                logger.warning("Can't censor %r: no timestamps", word["word"])
                continue
            spans.append((
                max(0, int(word["start"] * 1000) - padding_ms),
                min(audio_len_ms, int(word["end"] * 1000) + padding_ms),
            ))

        merged: list[tuple[int, int]] = []
        for start_ms, end_ms in sorted(spans):
            if merged and start_ms <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))
            else:
                merged.append((start_ms, end_ms))
        return merged

    def _make_filler(self, audio: AudioSegment, duration_ms: int, beep: bool) -> AudioSegment:
        """Silence or a beep of `duration_ms`, matching `audio`'s format.

        Same frame rate, channels and sample width as the source, so the
        pieces join without resampling.
        """
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
