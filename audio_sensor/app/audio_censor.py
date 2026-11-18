import warnings

# pyannote (used by WhisperX for voice-activity detection) warns that torchcodec
# can't load. Harmless: WhisperX hands it audio already decoded in memory.
warnings.filterwarnings("ignore", message=r"\s*torchcodec is not installed correctly")

import whisperx


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
            {key: float(val) if key != "word" else val for key, val in word.items()}
            for word in aligned["word_segments"]
        ]


# usage example (runs only when this file is executed directly, not on import):
if __name__ == "__main__":
    censor = AudioCensor(censor_words=["badword1", "badword2"])
    words = censor.transcribe_audio(
        r"C:\Users\Lenovo\Downloads\file_example_WAV_1MG.wav")
    for w in words:
        print(f"{w.get('start', '?'):>7} - {w.get('end', '?'):>7}  {w['word']}")
