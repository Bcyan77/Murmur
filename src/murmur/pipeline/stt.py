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

    # FunASR가 로드 가능한 것으로 확인된 HF 모델.
    _SUPPORTED_MODELS = {
        "FunAudioLLM/SenseVoiceSmall",
        "openai/whisper-large-v3-turbo",
    }

    def load_model(self) -> None:
        from funasr import AutoModel

        if self._config.model_name not in self._SUPPORTED_MODELS:
            raise RuntimeError(
                f"STT 모델 '{self._config.model_name}'은(는) 현재 지원되지 않습니다. "
                f"설정 → 모델 탭에서 다음 중 하나를 선택하세요: "
                f"{', '.join(sorted(self._SUPPORTED_MODELS))}"
            )

        # 먼저 HF 캐시에 모델을 내려받은 뒤 로컬 스냅샷 경로를 funasr에 전달한다.
        # repo ID로 전달하면 funasr가 configuration.json의 'model' 필드를
        # 제대로 읽지 못하고 repo ID를 클래스 이름으로 해석해 "not registered"
        # 오류가 발생하는 경우가 있다.
        model_path = self._ensure_downloaded(self._config.model_name)

        logger.info("Loading STT model: %s (from %s)", self._config.model_name, model_path)
        start = time.time()
        self._model = AutoModel(
            model=model_path,
            device=self._config.device,
            disable_update=True,
        )
        elapsed = time.time() - start
        logger.info(f"STT model loaded in {elapsed:.1f}s")

    @staticmethod
    def _ensure_downloaded(repo_id: str) -> str:
        """HF 스냅샷을 내려받고 로컬 디렉토리 경로를 반환한다."""
        from huggingface_hub import snapshot_download
        return snapshot_download(repo_id)

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
