"""실시간 오디오 캡처 → VAD → STT 통합 테스트.

시스템 오디오를 캡처하여 발화 단위로 전사 텍스트를 콘솔에 출력한다.
Ctrl+C로 종료.
"""

import signal
import sys
import time
from multiprocessing import Queue

from murmur.audio.capture import AudioCapture
from murmur.config import AudioConfig, STTConfig, VADConfig
from murmur.pipeline.stt import SpeechRecognizer
from murmur.pipeline.vad import VADSegmenter


def main():
    audio_config = AudioConfig()
    vad_config = VADConfig()
    stt_config = STTConfig()

    queue: Queue = Queue(maxsize=audio_config.queue_maxsize)

    print("Loading STT model...")
    stt = SpeechRecognizer(stt_config)
    stt.load_model()

    vad = VADSegmenter(vad_config, sample_rate=audio_config.sample_rate)

    print("Models loaded. Starting capture...")
    print("Play audio on your system. Press Ctrl+C to stop.\n")

    capture = AudioCapture(queue, audio_config)
    capture.start()

    running = True

    def on_sigint(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, on_sigint)

    segment_count = 0
    try:
        while running:
            if not queue.empty():
                chunk = queue.get()
                segment = vad.feed(chunk)
                if segment is not None:
                    result = stt.transcribe(segment, audio_config.sample_rate)
                    if result.text.strip():
                        segment_count += 1
                        print(
                            f"[{segment_count}] "
                            f"({result.language}) "
                            f"{result.text}  "
                            f"[{result.duration_ms:.0f}ms audio, "
                            f"{result.process_time_ms:.0f}ms proc]"
                        )
            else:
                time.sleep(0.01)
    finally:
        capture.stop()
        print(f"\nStopped. {segment_count} segments transcribed.")


if __name__ == "__main__":
    main()
