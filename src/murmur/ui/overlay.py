from __future__ import annotations

import ctypes
import platform

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from murmur.config import OverlayConfig

_IS_WINDOWS = platform.system() == "Windows"
_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020

# 화면 하단 여백 (픽셀)
_BOTTOM_MARGIN = 40
# 오버레이 가로 폭 비율 (화면 대비)
_WIDTH_RATIO = 0.80
# 내부 패딩
_PAD_H = 14  # 좌우
_PAD_V = 10  # 상하
_LINE_GAP = 6


class SubtitleOverlay(QWidget):
    """투명 배경 자막 오버레이 창.

    - 항상 최상위(WindowStaysOnTopHint), 프레임 없음, 태스크바 미표시
    - 기본 상태: WS_EX_TRANSPARENT로 마우스 이벤트를 하위 창에 투과
    - Alt 키를 누른 상태에서 좌클릭 드래그로 위치 이동
    """

    def __init__(self, config: OverlayConfig, parent=None) -> None:
        flags = (
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool  # 태스크바에 표시 안 함
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self._config = config
        self._original_text: str = ""
        self._translated_text: str = ""

        self._drag_active = False
        self._drag_offset = QPoint()
        self._alt_held = False
        self._click_through_applied = False

        # 초기 위치·크기 설정
        self._init_geometry()

        # Alt 키 상태 폴링 — 클릭 투과 ↔ 드래그 모드 전환
        if _IS_WINDOWS:
            self._key_timer = QTimer(self)
            self._key_timer.timeout.connect(self._poll_alt_key)
            self._key_timer.start(50)

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def update_subtitle(self, original: str, translated: str) -> None:
        """자막 텍스트를 갱신하고 창 높이를 재계산한다."""
        self._original_text = original
        self._translated_text = translated
        self._recalc_height()
        self.update()

    def clear_subtitle(self) -> None:
        self._original_text = ""
        self._translated_text = ""
        self.update()

    def update_config(self, config: OverlayConfig) -> None:
        """설정 변경 시 오버레이를 즉시 갱신한다."""
        self._config = config
        self.update()

    # ── Qt 이벤트 ──────────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # winId()는 네이티브 핸들 생성 후 유효하므로 이벤트 루프 실행 후 적용
        if _IS_WINDOWS and not self._click_through_applied:
            QTimer.singleShot(0, self._apply_initial_click_through)

    def paintEvent(self, event) -> None:
        if not self._translated_text:
            return

        tr_font = QFont(self._config.font_family, self._config.font_size)
        orig_font = QFont(self._config.font_family, max(self._config.font_size - 4, 12))
        tr_fm = QFontMetrics(tr_font)
        orig_fm = QFontMetrics(orig_font)

        text_w = self.width() - _PAD_H * 2
        lines: list[tuple[QFont, QFontMetrics, QColor, str]] = []

        if self._config.show_original and self._original_text:
            for line in _wrap_text(self._original_text, orig_fm, text_w)[: self._config.max_lines]:
                lines.append((orig_font, orig_fm, QColor(180, 180, 180), line))

        for line in _wrap_text(self._translated_text, tr_fm, text_w)[: self._config.max_lines]:
            lines.append((tr_font, tr_fm, QColor(self._config.font_color), line))

        if not lines:
            return

        total_h = _PAD_V * 2 + sum(fm.height() for _, fm, _, _ in lines) + _LINE_GAP * (len(lines) - 1)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bg_alpha = int(self._config.bg_opacity * 210)
        painter.setBrush(QColor(0, 0, 0, bg_alpha))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, self.width(), total_h, 10, 10)

        y = _PAD_V
        for font, fm, color, text in lines:
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(_PAD_H, y + fm.ascent(), text)
            y += fm.height() + _LINE_GAP

        painter.end()

    def mousePressEvent(self, event) -> None:
        if self._alt_held and event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event) -> None:
        if self._drag_active and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _init_geometry(self) -> None:
        screen = QApplication.primaryScreen().geometry()
        w = int(screen.width() * _WIDTH_RATIO)
        h = 80  # 텍스트 없을 때 기본 높이
        x = screen.left() + (screen.width() - w) // 2
        y = screen.bottom() - h - _BOTTOM_MARGIN
        self.setGeometry(x, y, w, h)

    def _recalc_height(self) -> None:
        """표시할 텍스트 기준으로 창 높이를 다시 계산하고 Y 위치를 조정한다."""
        if not self._translated_text:
            return

        tr_font = QFont(self._config.font_family, self._config.font_size)
        orig_font = QFont(self._config.font_family, max(self._config.font_size - 4, 12))
        tr_fm = QFontMetrics(tr_font)
        orig_fm = QFontMetrics(orig_font)

        text_w = self.width() - _PAD_H * 2
        n_lines = 0

        if self._config.show_original and self._original_text:
            n_lines += len(_wrap_text(self._original_text, orig_fm, text_w)[: self._config.max_lines])
            line_h = orig_fm.height()
        else:
            line_h = tr_fm.height()

        n_lines += len(_wrap_text(self._translated_text, tr_fm, text_w)[: self._config.max_lines])
        # 모든 줄의 높이를 번역 줄 기준으로 근사 (혼합이지만 큰 차이 없음)
        line_h = tr_fm.height()

        new_h = _PAD_V * 2 + n_lines * line_h + max(0, n_lines - 1) * _LINE_GAP

        screen = QApplication.primaryScreen().geometry()
        new_y = screen.bottom() - new_h - _BOTTOM_MARGIN
        self.setGeometry(self.x(), new_y, self.width(), new_h)

    def _apply_initial_click_through(self) -> None:
        if not self._click_through_applied:
            self._set_click_through(True)
            self._click_through_applied = True

    def _poll_alt_key(self) -> None:
        VK_MENU = 0x12  # Alt 키 가상 키 코드
        alt_held = bool(ctypes.windll.user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        if alt_held != self._alt_held:
            self._alt_held = alt_held
            # Alt 누름 → 드래그 가능(클릭 투과 해제), Alt 뗌 → 클릭 투과 복원
            self._set_click_through(not alt_held)

    def _set_click_through(self, enabled: bool) -> None:
        if not _IS_WINDOWS:
            return
        hwnd = int(self.winId())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        if enabled:
            style |= _WS_EX_TRANSPARENT
        else:
            style &= ~_WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style)


def _wrap_text(text: str, fm: QFontMetrics, max_width: int) -> list[str]:
    """텍스트를 max_width 픽셀에 맞게 단어 단위로 줄바꿈한다."""
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        if fm.horizontalAdvance(candidate) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]
