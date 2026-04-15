"""번역 버퍼 — STT 출력을 문장/절 단위로 모아서 번역 단위로 내보낸다.

한국어는 SOV 어순이라 단어 단위 번역이 부자연스러워, 짧은 발화를 누적해서
문장 경계에 도달했을 때 한꺼번에 번역해야 품질이 좋다.

플러시 조건:
1. 문장 종결 부호(.?!…。？！。) 포함
2. `max_chars` 초과
3. 마지막 입력 후 `flush_ms` 경과
4. 명시적 `flush()` 호출
"""
from __future__ import annotations

import time
from dataclasses import dataclass

# 문장 경계로 간주할 문자들.
_SENTENCE_END = set(".?!…。？！")


@dataclass
class BufferEntry:
    text: str
    language: str
    first_timestamp: float


class TranslationBuffer:
    def __init__(self, max_chars: int = 200, flush_ms: int = 1500) -> None:
        self._max_chars = max_chars
        self._flush_ms = flush_ms
        self._entries: list[BufferEntry] = []
        self._dominant_language: str = ""
        self._last_input_ts: float = 0.0

    def add(self, text: str, language: str, timestamp: float) -> BufferEntry | None:
        """새 STT 결과를 버퍼에 추가. 플러시 조건 충족 시 합쳐진 결과 반환."""
        text = text.strip()
        if not text:
            return self.maybe_timeout_flush(timestamp)

        # 감지 언어가 바뀌면 기존 버퍼는 먼저 내보내고 새 언어로 시작
        if self._dominant_language and language != self._dominant_language:
            flushed = self._emit()
            self._push(text, language, timestamp)
            if self._should_flush_on_punct(text):
                return self._emit() or flushed
            return flushed

        self._push(text, language, timestamp)

        if self._should_flush_on_punct(text) or self._over_limit():
            return self._emit()
        return None

    def maybe_timeout_flush(self, now: float) -> BufferEntry | None:
        if not self._entries:
            return None
        if (now - self._last_input_ts) * 1000 >= self._flush_ms:
            return self._emit()
        return None

    def flush(self) -> BufferEntry | None:
        return self._emit()

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _push(self, text: str, language: str, timestamp: float) -> None:
        if not self._entries:
            self._entries.append(BufferEntry(text, language, timestamp))
            self._dominant_language = language
        else:
            existing = self._entries[0]
            existing.text = f"{existing.text} {text}".strip()
        self._last_input_ts = timestamp

    def _should_flush_on_punct(self, text: str) -> bool:
        return bool(text) and text[-1] in _SENTENCE_END

    def _over_limit(self) -> bool:
        if not self._entries:
            return False
        return len(self._entries[0].text) >= self._max_chars

    def _emit(self) -> BufferEntry | None:
        if not self._entries:
            return None
        out = self._entries[0]
        self._entries.clear()
        self._dominant_language = ""
        return out


def now_ms() -> float:
    return time.time()
