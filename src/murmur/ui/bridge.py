from __future__ import annotations

from multiprocessing import Queue
from queue import Empty

from PySide6.QtCore import QThread, Signal

from murmur.pipeline.worker import PipelineResult


class ResultBridge(QThread):
    """result_queue를 폴링하여 Qt 시그널로 변환하는 워커 스레드.

    별도 스레드에서 multiprocessing.Queue를 블로킹 폴링하고,
    PipelineResult 도착 시 result_received 시그널을 emit한다.
    dict 타입 제어 메시지(ready/error)는 이미 wait_ready()에서 소비되므로 무시한다.
    """

    result_received: Signal = Signal(object)  # PipelineResult

    def __init__(self, result_queue: Queue, parent=None) -> None:
        super().__init__(parent)
        self._queue = result_queue
        self._running = False

    def run(self) -> None:
        self._running = True
        while self._running:
            try:
                item = self._queue.get(timeout=0.1)
            except Empty:
                continue
            if isinstance(item, PipelineResult):
                self.result_received.emit(item)

    def stop(self) -> None:
        self._running = False
        self.wait(2000)
