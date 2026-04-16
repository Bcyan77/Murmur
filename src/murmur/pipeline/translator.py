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

    def translate(self, text: str, source_lang: str = "auto") -> TranslationResult:
        if self._llm is None:
            raise RuntimeError("Model not loaded. Call load_model() first.")

        source_name = _LANG_CODE_TO_NAME.get(source_lang, source_lang)
        target_name = self._config.target_language

        # llama-cpp의 create_chat_completion은 GGUF에 포함된 채팅 템플릿을
        # 모델별로 자동 적용한다 (Aya, Qwen3, Llama 등 호환).
        # `/no_think`는 Qwen3의 thinking 모드 비활성 플래그. Aya 등 다른 모델은
        # 무시하므로 항상 포함해도 안전하다.
        system_msg = (
            f"/no_think You are a professional translator. Translate the user's "
            f"text from {source_name} to {target_name}. Reply with ONLY the "
            f"translation — no explanations, no tags, no thinking, no quotes."
        )

        start = time.time()
        output = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": text},
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
            target_language=target_name,
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
