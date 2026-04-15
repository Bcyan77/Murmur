from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QActionGroup, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from murmur.audio.capture import _is_process_loopback_supported
from murmur.audio.sessions import list_audio_sessions


class SystemTrayIcon(QSystemTrayIcon):
    """Murmur 시스템 트레이 아이콘 및 컨텍스트 메뉴."""

    start_requested = Signal()
    stop_requested = Signal()
    overlay_toggle_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()
    # (mode, pid): mode is "system" or "app"; pid is 0 for system mode
    audio_source_changed = Signal(str, int)

    def __init__(self, parent=None) -> None:
        super().__init__(_make_icon("idle"), parent)
        self.setToolTip("Murmur")
        self._is_running = False
        self._is_loading = False
        self._overlay_visible = False
        self._current_mode = "system"
        self._current_pid = 0
        self._source_menu: QMenu | None = None
        self._source_group: QActionGroup | None = None
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

    def set_audio_source(self, mode: str, pid: int) -> None:
        """현재 선택된 오디오 소스를 UI에 반영한다 (시그널 발생 없음)."""
        self._current_mode = mode
        self._current_pid = pid

    def show_info(self, message: str, msecs: int = 2000) -> None:
        self.showMessage("Murmur", message, QSystemTrayIcon.MessageIcon.Information, msecs)

    def show_error(self, message: str, msecs: int = 4000) -> None:
        self.showMessage("Murmur", message, QSystemTrayIcon.MessageIcon.Warning, msecs)

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        menu = QMenu()

        self._toggle_action = menu.addAction("시작")
        self._toggle_action.triggered.connect(self._on_toggle)

        self._source_menu = menu.addMenu("오디오 소스")
        menu.aboutToShow.connect(self._rebuild_source_menu)

        self._overlay_action = menu.addAction("자막 표시")
        self._overlay_action.triggered.connect(self.overlay_toggle_requested)

        menu.addSeparator()

        settings_action = menu.addAction("설정")
        settings_action.triggered.connect(self.settings_requested)

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

    def _rebuild_source_menu(self) -> None:
        """컨텍스트 메뉴가 열릴 때마다 오디오 세션 목록을 다시 읽어 구성한다."""
        menu = self._source_menu
        if menu is None:
            return
        menu.clear()

        group = QActionGroup(menu)
        group.setExclusive(True)

        system_action = menu.addAction("시스템 전체")
        system_action.setCheckable(True)
        system_action.setChecked(self._current_mode == "system")
        system_action.triggered.connect(
            lambda: self._select_source("system", 0)
        )
        group.addAction(system_action)

        menu.addSeparator()

        sessions = list_audio_sessions() if _is_process_loopback_supported() else []
        if not sessions:
            empty = menu.addAction("(오디오 출력 중인 앱 없음)")
            empty.setEnabled(False)
        else:
            for s in sessions:
                action = menu.addAction(f"{s.display_name}  (PID {s.pid})")
                action.setCheckable(True)
                action.setChecked(
                    self._current_mode == "app" and self._current_pid == s.pid
                )
                pid = s.pid
                action.triggered.connect(
                    lambda _checked=False, p=pid: self._select_source("app", p)
                )
                group.addAction(action)

        menu.addSeparator()
        refresh = menu.addAction("새로고침")
        refresh.triggered.connect(self._rebuild_source_menu)

        if not _is_process_loopback_supported():
            note = menu.addAction("(앱 지정은 Windows 10 2004+ 필요)")
            note.setEnabled(False)

        self._source_group = group

    def _select_source(self, mode: str, pid: int) -> None:
        if mode == self._current_mode and pid == self._current_pid:
            return
        self._current_mode = mode
        self._current_pid = pid
        self.audio_source_changed.emit(mode, pid)

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
