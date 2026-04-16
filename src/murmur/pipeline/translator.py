from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from murmur.config import TranslatorConfig

logger = logging.getLogger(__name__)

# Qwen3/DeepSeek 등 thinking 모델이 내는 내부 추론 블록
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ISO 639-1/639-2 코드를 Aya 프롬프트용 언어명으로 매핑
_LANG_CODE_TO_NAME = {
    "en": "English",
    "ja": "Japanese",
    "zh": "Chinese",
    "ko": "Korean",
    "yue": "Cantonese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "ru": "Russian",
    "auto": "the source language",
    "unknown": "the source language",
}


@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    source_language: str
    target_language: str
    process_time_ms: float


class Translator:
    def __init__(self, config: TranslatorConfig) -> None:
        self._config = config
        self._llm = None
        self._system_message: dict | None = None

    def load_model(self) -> None:
        if not self._config.model_path:
            raise ValueError(
                "translator.model_path is empty. "
                "Download a GGUF model and set the path in config."
            )

        from llama_cpp import Llama

        logger.info(f"Loading translation model: {self._config.model_path}")
        start = time.time()
        self._llm = Llama(
            model_path=self._config.model_path,
            n_ctx=self._config.n_ctx,
            n_gpu_layers=self._config.n_gpu_layers,
            verbose=False,
        )
        elapsed = time.time() - start
        logger.info(f"Translation model loaded in {elapsed:.1f}s")

        # 대상 언어 기반 시스템 프롬프트를 한 번만 구성한다.
        # source_lang을 포함하지 않아 프롬프트가 호출 간 불변이 되므로
        # llama.cpp KV 캐시가 시스템 프롬프트 토큰을 자동 재사용한다.
        # `/no_think`는 Qwen3 thinking 모드 비활성 플래그.
        target_name = self._config.target_language
        self._system_message = {
            "role": "system",
            "content": (
                f"/no_think You are a professional translator. "
                f"Translate the user's text to {target_name}. "
                f"Reply with ONLY the translation — no explanations, "
                f"no tags, no thinking, no quotes."
            ),
        }

        # 워밍업: 시스템 프롬프트 토큰을 미리 평가하여 KV 캐시에 적재
        self._llm.create_chat_completion(
            messages=[self._system_message, {"role": "user", "content": "Hi"}],
            max_tokens=1,
        )
        logger.info("Translation prompt cache warmed up")

    def translate(self, text: str, source_lang: str = "auto") -> TranslationResult:
        if self._llm is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        start = time.time()
        output = self._llm.create_chat_completion(
            messages=[
                self._system_message,               # 불변 — KV 캐시 히트
                {"role": "user", "content": text},   # 이것만 새로 평가
            ],
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
        )
        process_time_ms = (time.time() - start) * 1000

        raw = output["choices"][0]["message"]["content"]
        translated = _clean_translation(raw)

        return TranslationResult(
            original_text=text,
            translated_text=translated,
            source_language=source_lang,
            target_language=self._config.target_language,
            process_time_ms=process_time_ms,
        )


def _clean_translation(text: str) -> str:
    """모델이 내뱉은 원시 출력에서 thinking 블록과 군더더기 기호를 제거한다."""
    # 닫힌 <think>...</think> 블록 제거 (Qwen3, DeepSeek 등)
    text = _THINK_RE.sub("", text)
    # 마지막 </think> 뒤의 본문만 사용 (앞쪽 thinking 잔재 제거)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[-1]
    # 닫히지 않은 <think>가 남아있다면 max_tokens에 잘린 경우 — 이후 내용 전부 폐기
    if "<think>" in text.lower():
        text = text[: text.lower().index("<think>")]
    # 기타 앵글 태그성 토큰 제거
    text = re.sub(r"<[^>]{1,40}>", "", text)
    # 앞뒤 공백/따옴표
    text = text.strip().strip('"').strip("'").strip()
    return text
