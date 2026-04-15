from __future__ import annotations

import logging
import threading
from multiprocessing import Queue
from queue import Full

import numpy as np
import pyaudiowpatch as pyaudio
from scipy.signal import resample_poly

from murmur.config import AudioConfig

logger = logging.getLogger(__name__)


class BaseCapture:
    """캡처 전략 공통 베이스."""

    def __init__(self, audio_queue: Queue, config: AudioConfig) -> None:
        self._queue = audio_queue
        self._config = config
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("%s started", type(self).__name__)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("%s stopped", type(self).__name__)

    def _capture_loop(self) -> None:
        raise NotImplementedError

    def _push(self, audio: np.ndarray) -> None:
        try:
            self._queue.put_nowait(audio)
        except Full:
            logger.warning("Audio queue full, dropping chunk")


class SystemLoopbackCapture(BaseCapture):
    """시스템 전체 오디오 WASAPI Loopback 캡처."""

    def __init__(self, audio_queue: Queue, config: AudioConfig) -> None:
        super().__init__(audio_queue, config)
        self._pa: pyaudio.PyAudio | None = None

    def _capture_loop(self) -> None:
        self._pa = pyaudio.PyAudio()
        try:
            device = self._find_loopback_device()
            if device is None:
                logger.error("No WASAPI loopback device found")
                return

            src_rate = int(device["defaultSampleRate"])
            channels = device["maxInputChannels"]
            dst_rate = self._config.sample_rate

            frames_per_buffer = int(src_rate * self._config.chunk_duration_ms / 1000)

            stream = self._pa.open(
                format=pyaudio.paFloat32,
                channels=channels,
                rate=src_rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=frames_per_buffer,
            )

            logger.info(
                f"Capturing: {device['name']} "
                f"({src_rate}Hz, {channels}ch → {dst_rate}Hz mono)"
            )

            while self._running:
                data = stream.read(frames_per_buffer, exception_on_overflow=False)
                audio = np.frombuffer(data, dtype=np.float32)
                audio = _to_mono(audio, channels)
                if src_rate != dst_rate:
                    audio = _resample(audio, src_rate, dst_rate)
                self._push(audio)

            stream.stop_stream()
            stream.close()

        except Exception:
            logger.exception("Audio capture error")
        finally:
            if self._pa is not None:
                self._pa.terminate()
                self._pa = None

    def _find_loopback_device(self) -> dict | None:
        wasapi_info = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_output = self._pa.get_device_info_by_index(
            wasapi_info["defaultOutputDevice"]
        )
        default_name = default_output["name"]

        for i in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(i)
            if (
                dev.get("isLoopbackDevice")
                and dev["hostApi"] == wasapi_info["index"]
            ):
                if default_name in dev["name"]:
                    logger.info(f"Found loopback device: {dev['name']}")
                    return dev

        for i in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice"):
                logger.info(f"Fallback loopback device: {dev['name']}")
                return dev

        return None


# 하위 호환: 기존 테스트/코드가 AudioCapture를 import하므로 별칭 유지
AudioCapture = SystemLoopbackCapture


def create_capture(audio_queue: Queue, config: AudioConfig) -> BaseCapture:
    """`config.capture_mode`에 따라 적절한 캡처 전략을 반환한다.

    - "system": 시스템 전체 루프백
    - "app":    프로세스 지정 루프백 (Windows 10 2004+ 필요)
    지원 불가 상황에서는 시스템 모드로 폴백한다.
    """
    mode = config.capture_mode
    if mode == "app":
        if not _is_process_loopback_supported():
            logger.warning(
                "Process loopback not supported on this OS — falling back to system capture"
            )
            return SystemLoopbackCapture(audio_queue, config)
        try:
            from murmur.audio.process_capture import ProcessLoopbackCapture
        except ImportError as e:
            logger.warning("Process loopback unavailable (%s) — falling back", e)
            return SystemLoopbackCapture(audio_queue, config)

        if config.target_app_pid <= 0:
            logger.warning("App mode selected but no target PID — falling back to system")
            return SystemLoopbackCapture(audio_queue, config)

        return ProcessLoopbackCapture(audio_queue, config)

    return SystemLoopbackCapture(audio_queue, config)


def _is_process_loopback_supported() -> bool:
    """Windows 10 build 20348+ (실무상 2004+는 19041이지만 Process Loopback API는 20348부터 안정)."""
    import sys

    if sys.platform != "win32":
        return False
    try:
        ver = sys.getwindowsversion()
    except AttributeError:
        return False
    # Windows 10 2004 = build 19041. Process Loopback API 요구 최소 빌드.
    return ver.major >= 10 and ver.build >= 19041


def _to_mono(audio: np.ndarray, channels: int) -> np.ndarray:
    if channels == 1:
        return audio
    return audio.reshape(-1, channels).mean(axis=1).astype(np.float32)


def _resample(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    from math import gcd

    g = gcd(src_rate, dst_rate)
    up = dst_rate // g
    down = src_rate // g
    return resample_poly(audio, up, down).astype(np.float32)
