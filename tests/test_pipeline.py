"""전체 파이프라인 통합 테스트.

시스템 오디오 캡처 → 추론 프로세스(VAD → STT → 번역) → 콘솔 출력.
Ctrl+C로 종료.

사용법:
    python tests/test_pipeline.py [model_path]
"""

import io
import signal
import sys
import time
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from queue import Empty

from murmur.audio.capture import AudioCapture
from murmur.config import load_config
from murmur.pipeline.worker import InferenceWorker, PipelineResult


def main():
    config = load_config()

    if len(sys.argv) > 1:
        config.translator.model_path = sys.argv[1]

    if config.translator.model_path and not Path(config.translator.model_path).exists():
        print(f"Translator model not found: {config.translator.model_path}")
        return

    print("Starting inference worker (this may take a while to load models)...")
    worker = InferenceWorker(config)
    worker.start()

    if not worker.wait_ready(timeout=180):
        print("Worker failed to start")
        worker.stop()
        return

    print("Worker ready. Starting audio capture...")
    capture = AudioCapture(worker.audio_queue, config.audio)
    capture.start()

    print("Play audio on your system. Press Ctrl+C to stop.\n")

    running = True

    def on_sigint(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, on_sigint)

    count = 0
    try:
        while running:
            try:
                result = worker.result_queue.get(timeout=0.1)
            except Empty:
                continue

            if isinstance(result, PipelineResult):
                count += 1
                print(f"[{count}] ({result.source_language})")
                print(f"  原文: {result.original_text}")
                print(f"  번역: {result.translated_text}")
    finally:
        capture.stop()
        worker.stop()
        print(f"\nStopped. {count} segments processed.")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
