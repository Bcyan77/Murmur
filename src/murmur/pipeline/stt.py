from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import numpy as np

from murmur.config import STTConfig

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionResult:
    text: str
    language: str
    duration_ms: float
    process_time_ms: float


class SpeechRecognizer:
    def __init__(self, config: STTConfig) -> None:
        self._config = config
        self._model = None

    def load_model(self) -> None:
        from funasr import AutoModel

        logger.info(f"Loading STT model: {self._config.model_name}")
        start = time.time()
        self._model = AutoModel(
            model=self._config.model_name,
            device=self._config.device,
            hub="hf",
        )
        elapsed = time.time() - start
        logger.info(f"STT model loaded in {elapsed:.1f}s")

    def transcribe(
        self, audio: np.ndarray, sample_rate: int = 16000
    ) -> TranscriptionResult:
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        duration_ms = len(audio) / sample_rate * 1000

        start = time.time()
        res = self._model.generate(
            input=audio,
            cache={},
            language=self._config.language,
            use_itn=self._config.use_itn,
            batch_size_s=self._config.batch_size_s,
        )
        process_time_ms = (time.time() - start) * 1000

        if not res or not res[0].get("text"):
            return TranscriptionResult(
                text="",
                language="unknown",
                duration_ms=duration_ms,
                process_time_ms=process_time_ms,
            )

        raw_text = res[0]["text"]
        language = _extract_language(raw_text)
        clean_text = _postprocess(raw_text)

        return TranscriptionResult(
            text=clean_text,
            language=language,
            duration_ms=duration_ms,
            process_time_ms=process_time_ms,
        )


def _extract_language(raw_text: str) -> str:
    match = re.match(r"<\|(\w+)\|>", raw_text)
    if match:
        return match.group(1)
    return "unknown"


def _postprocess(raw_text: str) -> str:
    from funasr.utils.postprocess_utils import rich_transcription_postprocess

    return rich_transcription_postprocess(raw_text)
