import warnings
from typing import NotRequired, TypedDict

import whisperx
from better_profanity import Profanity

# pyannote (used by WhisperX for voice-activity detection) warns that torchcodec
# can't load. Harmless: WhisperX hands it audio already decoded in memory.
warnings.filterwarnings(
    "ignore", message=r"\s*torchcodec is not installed correctly")


class Word(TypedDict):
    word: str
    start: float
    end: float
    score: float
    flagged: NotRequired[bool]  # True if the word is in the censor list


class AudioCensor:
    DEVICE = "cpu"
    LANGUAGE = "en"

    def __init__(
        self,
        censor_words,
        model_name: str = "small",
        compute_type: str = "int8",
        batch_size: int = 8,
    ):
        self.censor_words = censor_words
        self.model_name = model_name
        # int8 is the fastest compute type on CPU; float16 is GPU-only.
        self.compute_type = compute_type
        self.batch_size = batch_size

        # better_profanity's built-in English word list plus our own censor
        # words. A per-instance Profanity (instead of the module-level
        # `profanity` singleton) keeps each AudioCensor's word list separate.
        self._profanity = Profanity()
        if censor_words:
            self._profanity.add_censor_words(censor_words)

        # Models are loaded lazily on first use and reused across calls,
        # because loading them takes far longer than transcribing a short clip.
        self._asr_model = None
        self._align_model = None
        self._align_metadata = None

    def censor_audio(self, audio_data):
        # Placeholder for audio processing logic
        # This method would analyze the audio data and censor any occurrences of the specified words
        censored_audio = audio_data  # In a real implementation, this would be modified
        return censored_audio

    def _load_models(self):
        if self._asr_model is None:
            self._asr_model = whisperx.load_model(
                self.model_name,
                self.DEVICE,
                compute_type=self.compute_type,
                language=self.LANGUAGE,
            )
        if self._align_model is None:
            self._align_model, self._align_metadata = whisperx.load_align_model(
                language_code=self.LANGUAGE,
                device=self.DEVICE,
            )

    def transcribe_audio(self, audio_path: str) -> list[dict]:
        """Transcribe English audio and force-align it to get word-level timestamps.

        Returns one dict per word, in order:
            {"word": str, "start": float, "end": float, "score": float}
        Times are in seconds. A word the aligner could not place (this can
        happen with numbers or symbols) has no "start"/"end"/"score" keys.
        """
        self._load_models()

        # Decodes any format ffmpeg understands into 16 kHz mono float32.
        audio = whisperx.load_audio(audio_path)

        result = self._asr_model.transcribe(
            audio,
            batch_size=self.batch_size,
            language=self.LANGUAGE,
        )

        aligned = whisperx.align(
            result["segments"],
            self._align_model,
            self._align_metadata,
            audio,
            self.DEVICE,
            return_char_alignments=False,
        )

        # The aligner returns numpy floats; convert them to plain Python floats
        # so the result is JSON-serializable (e.g. returned from FastAPI).
        return [
            {key: float(val) if key != "word" else val for key,
             val in word.items()}
            for word in aligned["word_segments"]
        ]

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


# usage example (runs only when this file is executed directly, not on import):
if __name__ == "__main__":
    censor = AudioCensor(censor_words=["badword1", "badword2"])
    words = censor.transcribe_audio(
        r"C:\Users\Lenovo\Downloads\freesound_community-fuck-36089.mp3")
    words = censor.detect_profanity(words)
    print(f"{'START':>7}  {'END':>7}  {'SCORE':>5}  {'FLAGGED':<7}  WORD")
    for w in words:
        # A word the aligner couldn't place has no start/end/score.
        start = f"{w['start']:.3f}" if "start" in w else "-"
        end = f"{w['end']:.3f}" if "end" in w else "-"
        score = f"{w['score']:.2f}" if "score" in w else "-"
        flagged = "YES" if w["flagged"] else "no"
        print(f"{start:>7}  {end:>7}  {score:>5}  {flagged:<7}  {w['word']}")

    flagged_count = sum(w["flagged"] for w in words)
    print(f"\n{len(words)} words, {flagged_count} flagged")
