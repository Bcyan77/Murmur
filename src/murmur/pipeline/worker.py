from __future__ import annotations

import logging
import multiprocessing as mp
import time
from dataclasses import dataclass
from multiprocessing import Queue
from queue import Empty, Full

from murmur.config import MurmurConfig

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    original_text: str
    translated_text: str
    source_language: str
    timestamp: float


# 제어 메시지 타입
READY = "ready"
ERROR = "error"
SENTINEL = None  # audio_queue에 넣어 종료 신호로 사용


class InferenceWorker:
    """추론 프로세스를 관리하는 컨트롤러.

    메인 프로세스에서 생성하여 start()/stop()으로 라이프사이클을 관리한다.
    audio_queue로 오디오 청크를 보내고 result_queue로 결과를 받는다.
    """

    def __init__(self, config: MurmurConfig) -> None:
        self._config = config
        self._audio_queue: Queue = mp.Queue(maxsize=config.audio.queue_maxsize)
        self._result_queue: Queue = mp.Queue(maxsize=50)
        self._process: mp.Process | None = None

    @property
    def audio_queue(self) -> Queue:
        return self._audio_queue

    @property
    def result_queue(self) -> Queue:
        return self._result_queue

    def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._process = mp.Process(
            target=_inference_loop,
            args=(self._audio_queue, self._result_queue, self._config),
            daemon=True,
        )
        self._process.start()
        logger.info(f"Inference process started (PID: {self._process.pid})")

    def wait_ready(self, timeout: float = 120.0) -> bool:
        """모델 로딩 완료 시그널을 대기한다."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = self._result_queue.get(timeout=1.0)
            except Empty:
                if self._process is None or not self._process.is_alive():
                    logger.error("Inference process died during startup")
                    return False
                continue

            if isinstance(msg, dict):
                if msg.get("type") == READY:
                    logger.info("Inference process ready")
                    return True
                if msg.get("type") == ERROR:
                    logger.error(f"Inference error: {msg.get('message')}")
                    return False
        logger.error("Timeout waiting for inference process")
        return False

    def stop(self, timeout: float = 10.0) -> None:
        if self._process is None:
            return
        try:
            self._audio_queue.put_nowait(SENTINEL)
        except Full:
            pass

        self._process.join(timeout=timeout)
        if self._process.is_alive():
            logger.warning("Inference process did not exit cleanly, terminating")
            self._process.terminate()
            self._process.join(timeout=5)
        self._process = None
        logger.info("Inference process stopped")


def _inference_loop(
    audio_queue: Queue, result_queue: Queue, config: MurmurConfig
) -> None:
    """추론 프로세스 메인 루프.

    모듈 최상위 함수여야 picklable 요구사항을 만족하고 spawn 방식에서 동작한다.
    """
    # 자식 프로세스 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(process)d %(name)s] %(levelname)s: %(message)s",
    )
    log = logging.getLogger("inference")

    # 모델 import는 자식 프로세스 내에서 (spawn 시 부모와 공유 안 됨)
    from murmur.pipeline.stt import SpeechRecognizer
    from murmur.pipeline.translator import Translator
    from murmur.pipeline.vad import VADSegmenter

    try:
        log.info("Loading models...")
        vad = VADSegmenter(config.vad, sample_rate=config.audio.sample_rate)
        stt = SpeechRecognizer(config.stt)
        stt.load_model()

        translator: Translator | None = None
        if config.translator.model_path:
            translator = Translator(config.translator)
            translator.load_model()
        else:
            log.warning("No translator model_path set; translation disabled")

        result_queue.put({"type": READY})
        log.info("Inference loop started")
    except Exception as e:
        log.exception("Failed to initialize inference process")
        try:
            result_queue.put({"type": ERROR, "message": str(e)})
        except Exception:
            pass
        return

    target_lang_code = _target_language_code(config.translator.target_language)

    try:
        while True:
            chunk = audio_queue.get()
            if chunk is SENTINEL:
                log.info("Sentinel received, exiting")
                break

            segment = vad.feed(chunk)
            if segment is None:
                continue

            stt_result = stt.transcribe(segment, config.audio.sample_rate)
            if not stt_result.text.strip():
                continue

            # 대상 언어와 동일하면 번역 생략
            if stt_result.language == target_lang_code or translator is None:
                translated = stt_result.text
            else:
                tr_result = translator.translate(stt_result.text, stt_result.language)
                translated = tr_result.translated_text

            result = PipelineResult(
                original_text=stt_result.text,
                translated_text=translated,
                source_language=stt_result.language,
                timestamp=time.time(),
            )

            _put_with_drop(result_queue, result, log)
    except Exception:
        log.exception("Inference loop error")
    finally:
        log.info("Inference loop terminated")


def _target_language_code(target_name: str) -> str:
    mapping = {
        "Korean": "ko",
        "English": "en",
        "Japanese": "ja",
        "Chinese": "zh",
    }
    return mapping.get(target_name, target_name.lower())


def _put_with_drop(queue: Queue, item, log: logging.Logger) -> None:
    """큐가 가득 차면 가장 오래된 항목을 버리고 새 항목을 넣는다."""
    try:
        queue.put_nowait(item)
    except Full:
        try:
            queue.get_nowait()
        except Empty:
            pass
        try:
            queue.put_nowait(item)
            log.warning("Result queue full, dropped oldest result")
        except Full:
            log.warning("Result queue still full after drop, skipping")
