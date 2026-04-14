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


class AudioCapture:
    def __init__(self, audio_queue: Queue, config: AudioConfig) -> None:
        self._queue = audio_queue
        self._config = config
        self._running = False
        self._thread: threading.Thread | None = None
        self._pa: pyaudio.PyAudio | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("Audio capture started")

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Audio capture stopped")

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

                try:
                    self._queue.put_nowait(audio)
                except Full:
                    logger.warning("Audio queue full, dropping chunk")

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

        # Fallback: any loopback device
        for i in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice"):
                logger.info(f"Fallback loopback device: {dev['name']}")
                return dev

        return None


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
