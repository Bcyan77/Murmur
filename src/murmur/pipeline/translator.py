from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from murmur.config import TranslatorConfig

logger = logging.getLogger(__name__)


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

        prompt = self._build_prompt(text, source_name, target_name)

        start = time.time()
        output = self._llm(
            prompt,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            stop=["<|END_OF_TURN_TOKEN|>", "\n\n"],
        )
        process_time_ms = (time.time() - start) * 1000

        translated = output["choices"][0]["text"].strip()

        return TranslationResult(
            original_text=text,
            translated_text=translated,
            source_language=source_lang,
            target_language=target_name,
            process_time_ms=process_time_ms,
        )

    def _build_prompt(self, text: str, source_lang: str, target_lang: str) -> str:
        return (
            f"<|START_OF_TURN_TOKEN|><|USER_TOKEN|>"
            f"Translate the following {source_lang} text to {target_lang}. "
            f"Only output the translation, nothing else.\n\n"
            f"{text}"
            f"<|END_OF_TURN_TOKEN|><|START_OF_TURN_TOKEN|><|CHATBOT_TOKEN|>"
        )
