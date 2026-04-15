from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

from murmur.audio.capture import BaseCapture, create_capture
from murmur.config import MurmurConfig, load_config, save_config
from murmur.pipeline.worker import InferenceWorker
from murmur.ui.bridge import ResultBridge
from murmur.ui.overlay import SubtitleOverlay
from murmur.ui.settings import SettingsDialog
from murmur.ui.tray import SystemTrayIcon
from murmur.ui.wizard import SetupWizard

logger = logging.getLogger(__name__)


class _WorkerLoader(QThread):
    """별도 스레드에서 InferenceWorker 모델 로딩 완료를 대기한다."""

    ready = Signal()
    failed = Signal(str)

    def __init__(self, worker: InferenceWorker, parent=None) -> None:
        super().__init__(parent)
        self._worker = worker

    def run(self) -> None:
        ok = self._worker.wait_ready(timeout=120.0)
        if ok:
            self.ready.emit()
        else:
            self.failed.emit("모델 로딩 실패 또는 타임아웃 (120초)")


class MurmurApp:
    """Murmur 애플리케이션 루트.

    QApplication 이벤트 루프를 소유하고, 오디오 캡처·추론 워커·UI 컴포넌트의
    라이프사이클을 관리한다.
    """

    def __init__(self) -> None:
        self.config: MurmurConfig = load_config()
        logger.info("Murmur config loaded")

        # 컴포넌트는 run() 호출 후 초기화 (QApplication 생성 후 Qt 객체 생성 필요)
        self._qt_app: QApplication | None = None
        self._worker: InferenceWorker | None = None
        self._capture: BaseCapture | None = None
        self._bridge: ResultBridge | None = None
        self._overlay: SubtitleOverlay | None = None
        self._tray: SystemTrayIcon | None = None
        self._loader: _WorkerLoader | None = None

    def run(self) -> int:
        self._qt_app = QApplication.instance() or QApplication(sys.argv)
        self._qt_app.setQuitOnLastWindowClosed(False)
        self._qt_app.setApplicationName("Murmur")

        # 추론 파이프라인 컴포넌트
        self._worker = InferenceWorker(self.config)
        self._capture = create_capture(self._worker.audio_queue, self.config.audio)
        self._bridge = ResultBridge(self._worker.result_queue)

        # UI 컴포넌트
        self._overlay = SubtitleOverlay(self.config.overlay)
        self._tray = SystemTrayIcon()
        self._tray.set_audio_source(
            self.config.audio.capture_mode, self.config.audio.target_app_pid
        )

        # 시그널 연결
        self._overlay.position_dragged.connect(self._on_overlay_dragged)
        self._tray.start_requested.connect(self._on_start)
        self._tray.stop_requested.connect(self._on_stop)
        self._tray.overlay_toggle_requested.connect(self._on_overlay_toggle)
        self._tray.settings_requested.connect(self._on_settings)
        self._tray.audio_source_changed.connect(self._on_audio_source_changed)
        self._tray.quit_requested.connect(self._on_quit)
        self._bridge.result_received.connect(self._on_result)

        self._tray.show()
        logger.info("Murmur started — tray icon visible")

        # 최초 실행 시 설정 마법사 표시
        if self.config.app.first_run:
            self._show_wizard()

        return self._qt_app.exec()

    # ── 슬롯 ──────────────────────────────────────────────────────────────────

    def _on_start(self) -> None:
        logger.info("Start requested")
        self._worker.start()
        self._tray.set_loading(True)
        self._tray.show_info("모델 로딩 중...", msecs=3000)

        self._loader = _WorkerLoader(self._worker)
        self._loader.ready.connect(self._on_worker_ready)
        self._loader.failed.connect(self._on_worker_failed)
        self._loader.start()

    def _on_worker_ready(self) -> None:
        logger.info("Worker ready — starting capture and bridge")
        self._capture.start()
        self._bridge.start()
        self._overlay.show()
        self._tray.set_running(True)
        self._tray.set_overlay_visible(True)
        self._tray.show_info("자막 번역 시작됨")

    def _on_worker_failed(self, message: str) -> None:
        logger.error(f"Worker failed: {message}")
        self._worker.stop()
        self._tray.set_running(False)
        self._tray.show_error(f"오류: {message}")

    def _on_stop(self) -> None:
        logger.info("Stop requested")
        self._capture.stop()
        self._bridge.stop()
        self._worker.stop()
        self._overlay.hide()
        self._overlay.clear_subtitle()
        self._tray.set_running(False)
        self._tray.set_overlay_visible(False)

    def _on_overlay_toggle(self) -> None:
        if self._overlay.isVisible():
            self._overlay.hide()
            self._tray.set_overlay_visible(False)
        else:
            self._overlay.show()
            self._tray.set_overlay_visible(True)

    def _on_result(self, result) -> None:
        # result: PipelineResult (Signal(object)로 전달됨)
        self._overlay.update_subtitle(result.original_text, result.translated_text)

    def _show_wizard(self) -> None:
        wizard = SetupWizard(self.config)
        wizard.wizard_completed.connect(self._on_wizard_completed)
        wizard.exec()

    def _on_wizard_completed(self, new_config: MurmurConfig) -> None:
        self.config = new_config
        self._overlay.update_config(new_config.overlay)
        logger.info("Setup wizard completed")

    def _on_overlay_dragged(self, x: int, y: int) -> None:
        self.config.overlay.position = "custom"
        self.config.overlay.custom_x = x
        self.config.overlay.custom_y = y
        save_config(self.config)
        logger.debug("Overlay dragged to (%d, %d)", x, y)

    def _on_audio_source_changed(self, mode: str, pid: int) -> None:
        logger.info("Audio source changed: mode=%s pid=%d", mode, pid)
        self.config.audio.capture_mode = mode
        self.config.audio.target_app_pid = pid
        save_config(self.config)

        # 실행 중이면 캡처만 재시작 (추론 워커는 유지)
        was_running = self._tray._is_running if self._tray else False
        if was_running and self._capture is not None:
            self._capture.stop()
            self._capture = create_capture(self._worker.audio_queue, self.config.audio)
            self._capture.start()
            label = "시스템 전체" if mode == "system" else f"PID {pid}"
            self._tray.show_info(f"오디오 소스 변경: {label}")
        else:
            self._capture = create_capture(self._worker.audio_queue, self.config.audio)

    def _on_settings(self) -> None:
        dialog = SettingsDialog(self.config)
        dialog.settings_applied.connect(self._on_settings_applied)
        dialog.exec()

    def _on_settings_applied(self, new_config: MurmurConfig) -> None:
        self.config = new_config
        # 오버레이 설정 즉시 반영
        self._overlay.update_config(new_config.overlay)
        logger.info("Settings applied")

    def _on_quit(self) -> None:
        logger.info("Quit requested")
        if self._capture:
            self._capture.stop()
        if self._bridge:
            self._bridge.stop()
        if self._worker:
            self._worker.stop()
        QApplication.quit()
