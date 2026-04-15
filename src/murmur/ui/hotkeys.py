"""Windows 전역 단축키 관리.

`RegisterHotKey` + QAbstractNativeEventFilter로 `WM_HOTKEY`를 가로챈다.
외부 의존성 없이 ctypes만 사용한다.
"""
from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes as wt

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

logger = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

# Win32 상수
_WM_HOTKEY = 0x0312
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000  # 꾹 눌러도 한 번만 발생

_MODIFIERS = {
    "ctrl": _MOD_CONTROL,
    "control": _MOD_CONTROL,
    "shift": _MOD_SHIFT,
    "alt": _MOD_ALT,
    "win": _MOD_WIN,
    "meta": _MOD_WIN,
    "super": _MOD_WIN,
}

# Qt가 사용하는 네이티브 이벤트 타입
_WIN_EVENT_TYPE = b"windows_generic_MSG"


def parse_hotkey(text: str) -> tuple[int, int] | None:
    """'ctrl+shift+m' 같은 문자열을 (modifiers, vk_code)로 파싱한다."""
    if not text:
        return None
    parts = [p.strip().lower() for p in text.split("+") if p.strip()]
    if not parts:
        return None

    mods = 0
    key = None
    for p in parts:
        if p in _MODIFIERS:
            mods |= _MODIFIERS[p]
        else:
            key = p

    if key is None:
        return None

    vk = _key_to_vk(key)
    if vk is None:
        return None
    return mods, vk


def _key_to_vk(key: str) -> int | None:
    key = key.lower()
    if len(key) == 1:
        ch = key.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)
    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)  # VK_F1 = 0x70
    # 기본 특수 키
    specials = {
        "space": 0x20,
        "enter": 0x0D,
        "return": 0x0D,
        "tab": 0x09,
        "esc": 0x1B,
        "escape": 0x1B,
        "backspace": 0x08,
        "delete": 0x2E,
        "home": 0x24,
        "end": 0x23,
        "pageup": 0x21,
        "pagedown": 0x22,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
    }
    return specials.get(key)


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, on_hotkey) -> None:
        super().__init__()
        self._on_hotkey = on_hotkey

    def nativeEventFilter(self, eventType, message):  # noqa: N802 (Qt)
        if eventType != _WIN_EVENT_TYPE:
            return False, 0
        try:
            msg = wt.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False, 0
        if msg.message == _WM_HOTKEY:
            self._on_hotkey(int(msg.wParam))
        return False, 0


class GlobalHotkeyManager(QObject):
    """Windows 전역 단축키를 등록·해제하고 시그널로 알린다.

    - `toggle_triggered`: 캡처 시작/정지 토글
    - `overlay_triggered`: 자막 오버레이 표시/숨김 토글
    - `settings_triggered`: 설정 창 열기
    """

    toggle_triggered = Signal()
    overlay_triggered = Signal()
    settings_triggered = Signal()

    _ID_TOGGLE = 1
    _ID_OVERLAY = 2
    _ID_SETTINGS = 3

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._registered: dict[int, str] = {}
        self._filter: _HotkeyFilter | None = None
        self._app = None

    def install(self, app) -> None:
        """QApplication에 네이티브 이벤트 필터를 설치한다."""
        if not _IS_WINDOWS or self._filter is not None:
            return
        self._filter = _HotkeyFilter(self._on_hotkey)
        app.installNativeEventFilter(self._filter)
        self._app = app

    def apply(
        self,
        hotkey_toggle: str,
        hotkey_overlay: str,
        hotkey_settings: str,
    ) -> list[str]:
        """현재 등록된 핫키를 해제하고 주어진 문자열로 재등록한다.

        등록 실패한 항목들의 문자열 리스트를 반환한다.
        """
        if not _IS_WINDOWS:
            return []

        self.unregister_all()
        failed: list[str] = []
        for hk_id, text in (
            (self._ID_TOGGLE, hotkey_toggle),
            (self._ID_OVERLAY, hotkey_overlay),
            (self._ID_SETTINGS, hotkey_settings),
        ):
            if not self._register(hk_id, text):
                failed.append(text)
        return failed

    def unregister_all(self) -> None:
        if not _IS_WINDOWS:
            return
        for hk_id in list(self._registered):
            ctypes.windll.user32.UnregisterHotKey(None, hk_id)
        self._registered.clear()

    # ── 내부 ─────────────────────────────────────────────────────────────────

    def _register(self, hk_id: int, text: str) -> bool:
        parsed = parse_hotkey(text)
        if parsed is None:
            logger.warning("Invalid hotkey spec: %r", text)
            return False
        mods, vk = parsed
        ok = ctypes.windll.user32.RegisterHotKey(
            None, hk_id, mods | _MOD_NOREPEAT, vk
        )
        if not ok:
            err = ctypes.get_last_error()
            logger.warning(
                "RegisterHotKey failed for %r (id=%d, err=%d)",
                text,
                hk_id,
                err,
            )
            return False
        self._registered[hk_id] = text
        logger.info("Hotkey registered: id=%d %r", hk_id, text)
        return True

    def _on_hotkey(self, hk_id: int) -> None:
        if hk_id == self._ID_TOGGLE:
            self.toggle_triggered.emit()
        elif hk_id == self._ID_OVERLAY:
            self.overlay_triggered.emit()
        elif hk_id == self._ID_SETTINGS:
            self.settings_triggered.emit()
