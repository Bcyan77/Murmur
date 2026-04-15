"""오디오 세션 열거 — 현재 오디오를 출력 중인 프로세스 목록을 조회한다.

UI에서 "앱 지정 캡처" 모드 선택 시 표시할 프로세스 목록 용도.
실제 프로세스별 오디오 캡처는 `process_capture.ProcessLoopbackCapture`가 담당.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioSession:
    pid: int
    name: str
    display_name: str

    def __str__(self) -> str:
        return f"{self.display_name} (PID {self.pid})"


def list_audio_sessions() -> list[AudioSession]:
    """현재 오디오 세션을 가진 프로세스 목록을 반환한다.

    Windows에서만 동작. 다른 플랫폼에서는 빈 리스트.
    시스템 프로세스(PID 0)는 제외.
    """
    if sys.platform != "win32":
        return []

    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        logger.warning("pycaw not available — returning empty session list")
        return []

    sessions: list[AudioSession] = []
    seen_pids: set[int] = set()

    try:
        raw_sessions = AudioUtilities.GetAllSessions()
    except Exception:
        logger.exception("Failed to enumerate audio sessions")
        return []

    for s in raw_sessions:
        if s.Process is None:
            continue
        pid = s.Process.pid
        if pid == 0 or pid in seen_pids:
            continue
        seen_pids.add(pid)

        try:
            name = s.Process.name()
        except Exception:
            name = "unknown"

        display = (s.DisplayName or "").strip() or name
        sessions.append(AudioSession(pid=pid, name=name, display_name=display))

    sessions.sort(key=lambda x: x.display_name.lower())
    return sessions
