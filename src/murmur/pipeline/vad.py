from __future__ import annotations

import logging

import numpy as np

from murmur.config import VADConfig

logger = logging.getLogger(__name__)


class VADSegmenter:
    """에너지 기반 침묵 감지로 발화 구간을 분리한다.

    오디오 청크를 받아 에너지(RMS)가 임계값 이상이면 발화로 판단하여 버퍼에 축적.
    침묵이 일정 시간 지속되면 축적된 오디오를 반환한다.
    SenseVoice의 내장 fsmn-vad가 세부 분할을 처리하므로 여기서는 대략적 분리만 담당.
    """

    def __init__(self, config: VADConfig, sample_rate: int = 16000) -> None:
        self._config = config
        self._sample_rate = sample_rate
        self._buffer: list[np.ndarray] = []
        self._buffer_samples: int = 0
        self._silence_samples: int = 0
        self._silence_threshold = int(config.silence_duration_ms / 1000 * sample_rate)
        self._max_samples = int(config.max_single_segment_time / 1000 * sample_rate)
        self._energy_threshold: float = 0.005
        self._has_speech = False

    def feed(self, chunk: np.ndarray) -> np.ndarray | None:
        energy = np.sqrt(np.mean(chunk ** 2))
        is_speech = energy > self._energy_threshold

        if is_speech:
            self._has_speech = True
            self._silence_samples = 0
            self._buffer.append(chunk)
            self._buffer_samples += len(chunk)
        else:
            if self._has_speech:
                self._buffer.append(chunk)
                self._buffer_samples += len(chunk)
                self._silence_samples += len(chunk)

                if self._silence_samples >= self._silence_threshold:
                    return self._flush()

        # Force flush if buffer exceeds max segment time
        if self._buffer_samples >= self._max_samples:
            logger.debug(
                f"Force flush: {self._buffer_samples / self._sample_rate:.1f}s"
            )
            return self._flush()

        return None

    def reset(self) -> None:
        self._buffer.clear()
        self._buffer_samples = 0
        self._silence_samples = 0
        self._has_speech = False

    def _flush(self) -> np.ndarray | None:
        if not self._buffer:
            return None

        audio = np.concatenate(self._buffer).astype(np.float32)
        self.reset()

        # Skip very short segments (< 0.3s)
        if len(audio) < self._sample_rate * 0.3:
            return None

        logger.debug(f"Segment: {len(audio) / self._sample_rate:.1f}s")
        return audio
