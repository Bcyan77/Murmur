from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class SystemTrayIcon(QSystemTrayIcon):
    """Murmur 시스템 트레이 아이콘 및 컨텍스트 메뉴."""

    start_requested = Signal()
    stop_requested = Signal()
    overlay_toggle_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(_make_icon("idle"), parent)
        self.setToolTip("Murmur")
        self._is_running = False
        self._is_loading = False
        self._overlay_visible = False
        self._setup_menu()

    # ── 상태 업데이트 ──────────────────────────────────────────────────────────

    def set_loading(self, loading: bool) -> None:
        self._is_loading = loading
        self._refresh_icon()
        self._refresh_actions()

    def set_running(self, running: bool) -> None:
        self._is_running = running
        self._is_loading = False
        self._refresh_icon()
        self._refresh_actions()

    def set_overlay_visible(self, visible: bool) -> None:
        self._overlay_visible = visible
        self._overlay_action.setText("자막 숨기기" if visible else "자막 표시")

    def show_info(self, message: str, msecs: int = 2000) -> None:
        self.showMessage("Murmur", message, QSystemTrayIcon.MessageIcon.Information, msecs)

    def show_error(self, message: str, msecs: int = 4000) -> None:
        self.showMessage("Murmur", message, QSystemTrayIcon.MessageIcon.Warning, msecs)

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        menu = QMenu()

        self._toggle_action = menu.addAction("시작")
        self._toggle_action.triggered.connect(self._on_toggle)

        self._overlay_action = menu.addAction("자막 표시")
        self._overlay_action.triggered.connect(self.overlay_toggle_requested)

        menu.addSeparator()

        quit_action = menu.addAction("종료")
        quit_action.triggered.connect(self.quit_requested)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_toggle(self) -> None:
        if self._is_loading:
            return
        if self._is_running:
            self.stop_requested.emit()
        else:
            self.start_requested.emit()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_toggle()

    def _refresh_actions(self) -> None:
        if self._is_loading:
            self._toggle_action.setText("로딩 중...")
            self._toggle_action.setEnabled(False)
        elif self._is_running:
            self._toggle_action.setText("정지")
            self._toggle_action.setEnabled(True)
        else:
            self._toggle_action.setText("시작")
            self._toggle_action.setEnabled(True)

    def _refresh_icon(self) -> None:
        if self._is_loading:
            self.setIcon(_make_icon("loading"))
        elif self._is_running:
            self.setIcon(_make_icon("running"))
        else:
            self.setIcon(_make_icon("idle"))


def _make_icon(state: str) -> QIcon:
    """상태별 트레이 아이콘을 생성한다 (32×32 픽셀)."""
    colors = {
        "idle": "#888888",
        "loading": "#FFA500",
        "running": "#00CC44",
    }
    color = colors.get(state, "#888888")

    px = QPixmap(32, 32)
    px.fill(QColor(0, 0, 0, 0))

    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor(color).darker(160))
    painter.drawEllipse(2, 2, 28, 28)

    font = QFont("Arial", 13, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(px.rect(), 0x84, "M")  # AlignCenter = 0x84

    painter.end()
    return QIcon(px)
