"""AudioCensor's pipeline with WhisperX replaced by fakes: when each model
loads, when alignment runs, and what the output file contains. The audio
files themselves are real (generated tones)."""

import shutil
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
import whisperx
from pydub import AudioSegment
from pydub.generators import Sine

from app.audio_censor import AudioCensor


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Stand-ins for the WhisperX calls AudioCensor makes, counting each."""
    state = SimpleNamespace(
        segments=[],  # what "transcription" returns
        word_segments=[],  # what "alignment" returns
        asr_loads=0,
        align_loads=0,
        align_calls=0,
        load_kwargs={},
    )

    class FakeASR:
        def transcribe(self, audio, batch_size, language):
            return {"segments": state.segments}

    def load_model(*args, **kwargs):
        state.asr_loads += 1
        state.load_kwargs = kwargs
        return FakeASR()

    def load_align_model(**kwargs):
        state.align_loads += 1
        return object(), {}

    def align(segments, model, metadata, audio, device, return_char_alignments):
        state.align_calls += 1
        return {"word_segments": state.word_segments}

    monkeypatch.setattr(whisperx, "load_model", load_model)
    monkeypatch.setattr(whisperx, "load_align_model", load_align_model)
    monkeypatch.setattr(whisperx, "align", align)
    monkeypatch.setattr(whisperx, "load_audio", lambda path: np.zeros(16000, dtype=np.float32))
    return state


@pytest.fixture
def tone(tmp_path: Path) -> Path:
    """Two seconds of a 440 Hz tone, as WAV."""
    path = tmp_path / "in.wav"
    Sine(440).to_audio_segment(duration=2000, volume=-10).export(path, format="wav")
    return path


def say(
    fake: SimpleNamespace, text: str, words: Sequence[tuple[str, float, float]] = ()
) -> None:
    fake.segments = [{"text": text, "start": 0.0, "end": 2.0}]
    fake.word_segments = [{"word": w, "start": s, "end": e, "score": 0.9} for w, s, e in words]


def test_clean_audio_skips_alignment_and_is_copied(fake, tone: Path, tmp_path: Path) -> None:
    say(fake, " Hello there, friend.")
    out = tmp_path / "out.wav"

    _, words = AudioCensor().censor_audio(str(tone), output_path=str(out))

    assert fake.align_loads == 0 and fake.align_calls == 0  # model never loaded
    assert out.read_bytes() == tone.read_bytes()  # copied, not re-encoded
    assert [w["word"] for w in words] == ["Hello", "there,", "friend."]
    assert not any(w.get("flagged") for w in words)


def test_profane_audio_is_aligned_and_muted(fake, tone: Path, tmp_path: Path) -> None:
    say(fake, " oh shit no", [("oh", 0.1, 0.3), ("shit", 0.8, 1.2), ("no", 1.5, 1.8)])
    out = tmp_path / "out.wav"

    _, words = AudioCensor().censor_audio(str(tone), output_path=str(out), padding_ms=100)

    assert fake.align_loads == 1 and fake.align_calls == 1
    assert [w["word"] for w in words if w.get("flagged")] == ["shit"]
    result = AudioSegment.from_file(out)
    assert result[700:1300].rms == 0  # the word, padded by 100 ms, is silent
    assert result[100:600].rms > 0 and result[1400:1900].rms > 0  # the rest isn't
    assert len(result) == len(AudioSegment.from_file(tone))


def test_models_load_once_and_only_when_needed(fake, tone: Path, tmp_path: Path) -> None:
    censor = AudioCensor()
    assert fake.asr_loads == 0  # nothing loads at construction

    say(fake, " all clean here")
    censor.censor_audio(str(tone), output_path=str(tmp_path / "1.wav"))
    assert (fake.asr_loads, fake.align_loads) == (1, 0)

    say(fake, " damn", [("damn", 0.5, 0.9)])
    censor.censor_audio(str(tone), output_path=str(tmp_path / "2.wav"))
    censor.censor_audio(str(tone), output_path=str(tmp_path / "3.wav"))
    assert (fake.asr_loads, fake.align_loads) == (1, 1)  # loaded once, then reused
    assert fake.align_calls == 2


def test_custom_censor_words_trigger_alignment(fake, tone: Path, tmp_path: Path) -> None:
    say(fake, " I like banana", [("I", 0.1, 0.2), ("like", 0.3, 0.5), ("banana", 0.6, 1.0)])

    _, words = AudioCensor(censor_words=["banana"]).censor_audio(
        str(tone), output_path=str(tmp_path / "out.wav")
    )

    assert fake.align_calls == 1
    assert [w["word"] for w in words if w.get("flagged")] == ["banana"]


def test_transcription_threads(fake, tone: Path, tmp_path: Path) -> None:
    say(fake, " clean")
    AudioCensor(threads=3).censor_audio(str(tone), output_path=str(tmp_path / "a.wav"))
    assert fake.load_kwargs["threads"] == 3

    fake.asr_loads = 0
    AudioCensor().censor_audio(str(tone), output_path=str(tmp_path / "b.wav"))
    assert fake.load_kwargs["threads"] == torch.get_num_threads()  # one per physical core


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_clean_audio_in_another_output_format_is_converted(
    fake, tone: Path, tmp_path: Path
) -> None:
    say(fake, " clean")
    out = tmp_path / "out.flac"

    AudioCensor().censor_audio(str(tone), output_path=str(out))

    assert fake.align_calls == 0
    converted = AudioSegment.from_file(out)
    assert abs(len(converted) - 2000) < 50


def test_unchanged_output_can_be_skipped(fake, tone: Path, tmp_path: Path) -> None:
    """The worker asks for no copy of a clean file in the same format."""
    say(fake, " clean")
    out = tmp_path / "out.wav"

    written, words = AudioCensor().censor_audio(str(tone), output_path=str(out), copy_unchanged=False)

    assert written is None
    assert not out.exists()
    assert [w["word"] for w in words] == ["clean"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_unchanged_output_in_another_format_is_still_written(
    fake, tone: Path, tmp_path: Path
) -> None:
    say(fake, " clean")
    out = tmp_path / "out.flac"

    written, _ = AudioCensor().censor_audio(str(tone), output_path=str(out), copy_unchanged=False)

    assert written == str(out) and out.exists()  # a conversion, not a copy
