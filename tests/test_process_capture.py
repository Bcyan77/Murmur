"""프로세스 지정 오디오 캡처 테스트.

사용법: python tests/test_process_capture.py [PID]
인자 없이 실행하면 첫 번째 오디오 세션의 PID를 자동 선택.
해당 앱이 실제로 소리를 내고 있어야 데이터가 들어온다.
"""
import io
import sys
import time
from multiprocessing import Queue
from queue import Empty

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from murmur.audio.process_capture import ProcessLoopbackCapture
from murmur.audio.sessions import list_audio_sessions
from murmur.config import AudioConfig


def main() -> None:
    if len(sys.argv) > 1:
        pid = int(sys.argv[1])
    else:
        sessions = list_audio_sessions()
        if not sessions:
            print("오디오 세션이 없습니다. 브라우저로 영상을 틀고 다시 실행하세요.")
            return
        pid = sessions[0].pid
        print(f"자동 선택: {sessions[0]}")

    config = AudioConfig(capture_mode="app", target_app_pid=pid)
    queue: Queue = Queue(maxsize=config.queue_maxsize)
    capture = ProcessLoopbackCapture(queue, config)
    capture.start()

    duration = 5.0
    start = time.time()
    chunks = 0
    total_samples = 0
    try:
        while time.time() - start < duration:
            try:
                chunk = queue.get(timeout=0.5)
            except Empty:
                continue
            chunks += 1
            total_samples += len(chunk)
    finally:
        capture.stop()

    elapsed = time.time() - start
    print(f"결과: {chunks} chunks / {total_samples} samples in {elapsed:.1f}s")
    if chunks == 0:
        print("  → 오디오가 들어오지 않았습니다. 대상 앱이 실제로 소리를 내는지 확인.")
    else:
        rms = total_samples / elapsed / 16000
        print(f"  → 평균 입력율: {rms:.2f}x realtime @ 16kHz")


if __name__ == "__main__":
    main()
