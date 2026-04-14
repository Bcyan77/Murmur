"""캡처된 WAV 파일로 STT를 테스트하는 스크립트."""

import sys
from pathlib import Path

import soundfile as sf

from murmur.config import STTConfig
from murmur.pipeline.stt import SpeechRecognizer


def main():
    wav_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test_capture_output.wav")

    if not wav_path.exists():
        print(f"WAV file not found: {wav_path}")
        print("Run test_capture.py first to record system audio.")
        return

    audio, sr = sf.read(str(wav_path), dtype="float32")
    print(f"Loaded {wav_path}: {len(audio)} samples, {sr}Hz, {len(audio)/sr:.1f}s")

    config = STTConfig()
    recognizer = SpeechRecognizer(config)
    print("Loading SenseVoice model (first run downloads from HuggingFace)...")
    recognizer.load_model()

    result = recognizer.transcribe(audio, sr)
    print(f"\n--- STT Result ---")
    print(f"Language: {result.language}")
    print(f"Text: {result.text}")
    print(f"Audio duration: {result.duration_ms:.0f}ms")
    print(f"Process time: {result.process_time_ms:.0f}ms")


if __name__ == "__main__":
    main()
