"""5초간 시스템 오디오를 캡처하여 WAV 파일로 저장하는 테스트 스크립트."""

import time
from multiprocessing import Queue
from pathlib import Path

import numpy as np
import soundfile as sf

from murmur.audio.capture import AudioCapture
from murmur.config import AudioConfig


def main():
    config = AudioConfig()
    queue: Queue = Queue(maxsize=config.queue_maxsize)

    capture = AudioCapture(queue, config)
    capture.start()

    print(f"Capturing system audio for 5 seconds... (rate={config.sample_rate}Hz)")
    chunks = []
    start = time.time()

    while time.time() - start < 5:
        if not queue.empty():
            chunk = queue.get()
            chunks.append(chunk)
        else:
            time.sleep(0.01)

    capture.stop()

    if not chunks:
        print("No audio captured. Is audio playing on your system?")
        return

    audio = np.concatenate(chunks)
    out_path = Path("test_capture_output.wav")
    sf.write(str(out_path), audio, config.sample_rate)
    print(f"Saved {len(audio)} samples ({len(audio)/config.sample_rate:.1f}s) to {out_path}")


if __name__ == "__main__":
    main()
