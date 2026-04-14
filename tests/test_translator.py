"""번역 모듈 단독 테스트.

모델 경로를 인자로 전달하거나 config에 설정한 후 실행한다.
    python tests/test_translator.py [model_path]
"""

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from murmur.config import TranslatorConfig, load_config
from murmur.pipeline.translator import Translator


def main():
    if len(sys.argv) > 1:
        config = TranslatorConfig(model_path=sys.argv[1])
    else:
        full = load_config()
        config = full.translator

    if not config.model_path or not Path(config.model_path).exists():
        print("Translator model not found.")
        print("Run: python scripts/download_models.py")
        print("Then set [translator] model_path in config.toml or pass as arg.")
        return

    translator = Translator(config)
    print(f"Loading model: {config.model_path}")
    translator.load_model()

    test_cases = [
        ("Hello, how are you today?", "en"),
        ("The weather is nice.", "en"),
        ("こんにちは、元気ですか？", "ja"),
    ]

    for text, lang in test_cases:
        print(f"\n[{lang}] {text}")
        result = translator.translate(text, lang)
        print(f"  → {result.translated_text}")
        print(f"  ({result.process_time_ms:.0f}ms)")


if __name__ == "__main__":
    main()
