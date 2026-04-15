"""초기 설정 마법사 (4단계).

Step 1: PC 사양 감지 + 프리셋 권장
Step 2: 모델 다운로드 상태 확인
Step 3: 언어 설정
Step 4: 기본 테스트
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from murmur.config import MurmurConfig, save_config
from murmur.hardware import HardwareInfo, detect_hardware
from murmur.presets import (
    PRESETS,
    Preset,
    PresetID,
    get_preset,
    is_preset_runnable,
    recommend_preset,
)

_TARGET_LANGUAGES = [
    ("한국어", "Korean"),
    ("영어", "English"),
    ("일본어", "Japanese"),
    ("중국어", "Chinese"),
]

_SOURCE_LANGUAGE_PRESETS = [
    ("영어", "en"),
    ("일본어", "ja"),
    ("중국어", "zh"),
    ("광둥어", "yue"),
    ("자동 감지 (모든 언어)", "auto"),
]


from murmur.ui.model_download import DownloadRow as _DownloadRow
from murmur.ui.model_download import ModelDownloadThread as _ModelDownloadThread  # noqa: F401 (레거시 참조)
from murmur.ui.model_download import estimate_repo_size as _estimate_repo_size  # noqa: F401


# ── 백그라운드 스레드 ──────────────────────────────────────────────────────────

class _HardwareDetectThread(QThread):
    detected = Signal(object)  # HardwareInfo

    def run(self) -> None:
        hw = detect_hardware()
        self.detected.emit(hw)


# ── 각 단계 위젯 ──────────────────────────────────────────────────────────────

class _Step1Widget(QWidget):
    """Step 1: PC 사양 감지 + 프리셋 권장."""

    preset_selected = Signal(str)  # preset_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hw: HardwareInfo | None = None
        self._setup_ui()
        self._detect()

    def selected_preset(self) -> str:
        for btn in self._preset_btns:
            if btn.isChecked():
                return btn.property("preset_id")
        return "korean_optimized"

    def hardware_info(self) -> HardwareInfo | None:
        return self._hw

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Step 1 / 4 — PC 사양 감지")
        title.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # 하드웨어 정보 박스
        hw_group = QGroupBox("감지된 사양")
        hw_layout = QVBoxLayout(hw_group)
        self._hw_label = QLabel("사양을 감지하는 중...")
        self._hw_label.setTextFormat(Qt.TextFormat.PlainText)
        self._hw_label.setWordWrap(True)
        hw_layout.addWidget(self._hw_label)
        layout.addWidget(hw_group)

        # 프리셋 선택
        preset_group = QGroupBox("모델 프리셋 선택")
        preset_layout = QVBoxLayout(preset_group)
        self._preset_group = QButtonGroup(self)
        self._preset_btns: list[QRadioButton] = []

        for preset in PRESETS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)

            btn = QRadioButton(preset.name)
            btn.setProperty("preset_id", preset.id.value)
            btn.toggled.connect(
                lambda checked, pid=preset.id.value: (
                    self.preset_selected.emit(pid) if checked else None
                )
            )
            self._preset_group.addButton(btn)
            self._preset_btns.append(btn)

            stars = "★" * preset.quality_stars + "☆" * (5 - preset.quality_stars)
            star_lbl = QLabel(stars)
            star_lbl.setStyleSheet("color: #FFA500;")
            star_lbl.setFixedWidth(70)

            self._update_btn_ref = None  # 나중에 비활성화 시 참조용
            row_layout.addWidget(btn)
            row_layout.addStretch()
            row_layout.addWidget(star_lbl)

            # 요구사양 레이블
            req = (
                f"VRAM {preset.required_vram_gb:.0f}GB+" if preset.requires_cuda else "CPU 전용"
            )
            req_lbl = QLabel(req)
            req_lbl.setStyleSheet("color: gray; font-size: 11px;")
            req_lbl.setFixedWidth(110)
            row_layout.addWidget(req_lbl)

            preset_layout.addWidget(row)

        layout.addWidget(preset_group)
        layout.addStretch()

    def _detect(self) -> None:
        self._thread = _HardwareDetectThread(self)
        self._thread.detected.connect(self._on_detected)
        self._thread.start()

    def _on_detected(self, hw: HardwareInfo) -> None:
        self._hw = hw
        self._hw_label.setText(hw.summary())

        recommended = recommend_preset(hw)

        for btn in self._preset_btns:
            pid = btn.property("preset_id")
            preset = next((p for p in PRESETS if p.id.value == pid), None)
            if preset is None:
                continue
            runnable, reason = is_preset_runnable(preset, hw)
            btn.setEnabled(runnable)

            if not runnable:
                btn.setText(f"{preset.name}  ← {reason}")
                btn.setStyleSheet("color: gray;")
            elif pid == recommended.value:
                btn.setText(f"{preset.name}  ← 권장")
                btn.setStyleSheet("font-weight: bold;")

            if pid == recommended.value and runnable:
                btn.setChecked(True)
            elif pid == recommended.value and not runnable:
                # 권장 프리셋을 실행할 수 없으면 저사양으로 폴백
                pass

        # 권장 프리셋이 비활성이면 저사양을 선택
        checked_any = any(btn.isChecked() for btn in self._preset_btns)
        if not checked_any:
            for btn in self._preset_btns:
                if btn.isEnabled():
                    btn.setChecked(True)
                    break


class _Step2Widget(QWidget):
    """Step 2: 모델 다운로드 상태."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._preset: Preset | None = None
        self._download_rows: dict[str, _DownloadRow] = {}
        self._setup_ui()

    def set_preset(self, preset: Preset) -> None:
        self._preset = preset
        self._refresh_models()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Step 2 / 4 — 모델 다운로드")
        title.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        note = QLabel(
            "선택한 프리셋에 필요한 모델 목록입니다.\n"
            "HuggingFace 모델은 [다운로드] 버튼으로 자동 설치되며,\n"
            "GGUF 모델은 직접 다운로드 후 설정에서 경로를 지정해야 합니다."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555;")
        layout.addWidget(note)

        self._models_group = QGroupBox("필요 모델")
        self._models_layout = QVBoxLayout(self._models_group)
        layout.addWidget(self._models_group)

        layout.addStretch()

    def _refresh_models(self) -> None:
        # 이전 위젯 제거
        while self._models_layout.count():
            item = self._models_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._download_rows.clear()

        if self._preset is None:
            return

        for spec in [self._preset.stt, self._preset.translator, self._preset.vad]:
            row = _DownloadRow(spec.name, spec.model_id, spec.size_mb, spec.source)
            self._download_rows[spec.model_id] = row
            self._models_layout.addWidget(row)


class _Step3Widget(QWidget):
    """Step 3: 언어 설정."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def source_language(self) -> str:
        for btn, code in self._lang_btns:
            if btn.isChecked():
                return code
        return "auto"

    def target_language(self) -> str:
        for btn, code in self._target_btns:
            if btn.isChecked():
                return code
        return "Korean"

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Step 3 / 4 — 언어 설정")
        title.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        note = QLabel(
            "캡처할 원본 언어와 표시할 자막 언어를 선택하세요.\n"
            "설정 창에서 언제든지 변경할 수 있습니다."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555;")
        layout.addWidget(note)

        # 원본 언어
        src_group = QGroupBox("원본 언어")
        src_layout = QVBoxLayout(src_group)
        self._lang_btns: list[tuple[QRadioButton, str]] = []
        src_btn_group = QButtonGroup(self)

        for label, code in _SOURCE_LANGUAGE_PRESETS:
            btn = QRadioButton(label)
            src_btn_group.addButton(btn)
            self._lang_btns.append((btn, code))
            src_layout.addWidget(btn)
            if code == "auto":
                btn.setChecked(True)
        layout.addWidget(src_group)

        # 자막 언어
        tgt_group = QGroupBox("자막 언어")
        tgt_layout = QVBoxLayout(tgt_group)
        self._target_btns: list[tuple[QRadioButton, str]] = []
        tgt_btn_group = QButtonGroup(self)

        for label, code in _TARGET_LANGUAGES:
            btn = QRadioButton(label)
            tgt_btn_group.addButton(btn)
            self._target_btns.append((btn, code))
            tgt_layout.addWidget(btn)
            if code == "Korean":
                btn.setChecked(True)
        layout.addWidget(tgt_group)

        layout.addStretch()


class _Step4Widget(QWidget):
    """Step 4: 기본 테스트."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Step 4 / 4 — 설정 완료")
        title.setFont(QFont("", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        ready_lbl = QLabel(
            "초기 설정이 완료되었습니다.\n\n"
            "설정을 저장하고 앱을 시작할 준비가 되었습니다.\n"
            "[완료] 버튼을 클릭하면 시스템 트레이에 Murmur가 상주합니다.\n\n"
            "시작 방법:\n"
            "  • 트레이 아이콘 우클릭 → [시작]\n"
            "  • 또는 트레이 아이콘 더블클릭\n\n"
            "오디오 소스 선택:\n"
            "  • 트레이 메뉴에서 [시스템 전체 오디오] 또는 앱 지정 (Phase 5 예정)\n\n"
            "설정 변경:\n"
            "  • 트레이 메뉴 → [설정]\n"
        )
        ready_lbl.setWordWrap(True)
        ready_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(ready_lbl)
        layout.addStretch()


# ── 마법사 다이얼로그 ──────────────────────────────────────────────────────────

class SetupWizard(QDialog):
    """초기 설정 마법사 다이얼로그.

    완료 시 설정이 저장되고 accepted 시그널이 emit된다.
    """

    wizard_completed = Signal(object)  # MurmurConfig

    def __init__(self, config: MurmurConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Murmur 초기 설정")
        self.setMinimumSize(520, 460)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        self._config = copy.deepcopy(config)
        self._setup_ui()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 트레이 앱은 주 창이 없으므로 마법사가 뒤에 숨지 않도록 명시적으로 전면화
        self.raise_()
        self.activateWindow()

    def get_config(self) -> MurmurConfig:
        return self._config

    # ── 닫기 처리 ──────────────────────────────────────────────────────────────

    def reject(self) -> None:
        """X 버튼/Esc 등으로 닫을 때: 실행 중 스레드만 정리하고 설정은 건드리지 않는다.

        사용자가 취소한 경우 `first_run` 플래그를 그대로 두어 다음 실행 때
        다시 마법사가 나타나도록 한다.
        """
        self._cleanup_threads()
        super().reject()

    def _cleanup_threads(self) -> None:
        threads = [getattr(self._step1, "_thread", None)]
        for row in getattr(self._step2, "_download_rows", {}).values():
            threads.append(getattr(row, "_thread", None))

        for t in threads:
            if t is None or not t.isRunning():
                continue
            t.quit()
            if not t.wait(2000):
                t.terminate()
                t.wait(1000)

    # ── UI 구성 ────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 스텝 인디케이터
        self._step_indicator = _StepIndicator(4)
        layout.addWidget(self._step_indicator)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # 스텝 콘텐츠 (StackedWidget)
        self._stack = QStackedWidget()

        self._step1 = _Step1Widget()
        self._step2 = _Step2Widget()
        self._step3 = _Step3Widget()
        self._step4 = _Step4Widget()

        self._step1.preset_selected.connect(self._on_preset_selected)

        self._stack.addWidget(self._step1)
        self._stack.addWidget(self._step2)
        self._stack.addWidget(self._step3)
        self._stack.addWidget(self._step4)
        layout.addWidget(self._stack, stretch=1)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        # 네비게이션 버튼
        nav = QWidget()
        nav_layout = QHBoxLayout(nav)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        self._prev_btn = QPushButton("이전")
        self._next_btn = QPushButton("다음")
        self._prev_btn.setFixedWidth(80)
        self._next_btn.setFixedWidth(80)
        self._prev_btn.clicked.connect(self._go_prev)
        self._next_btn.clicked.connect(self._go_next)
        nav_layout.addStretch()
        nav_layout.addWidget(self._prev_btn)
        nav_layout.addWidget(self._next_btn)
        layout.addWidget(nav)

        self._update_nav()

    # ── 네비게이션 ─────────────────────────────────────────────────────────────

    def _current_step(self) -> int:
        return self._stack.currentIndex()

    def _go_prev(self) -> None:
        idx = self._current_step()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
            self._step_indicator.set_step(idx - 1)
            self._update_nav()

    def _go_next(self) -> None:
        idx = self._current_step()
        if idx < self._stack.count() - 1:
            self._stack.setCurrentIndex(idx + 1)
            self._step_indicator.set_step(idx + 1)
            self._update_nav()
            self._on_step_entered(idx + 1)
        else:
            self._finish()

    def _update_nav(self) -> None:
        idx = self._current_step()
        self._prev_btn.setEnabled(idx > 0)
        is_last = idx == self._stack.count() - 1
        self._next_btn.setText("완료" if is_last else "다음")

    def _on_step_entered(self, step: int) -> None:
        """각 스텝 진입 시 처리."""
        if step == 1:
            # Step 2: 선택된 프리셋 반영
            pid = self._step1.selected_preset()
            preset = next((p for p in PRESETS if p.id.value == pid), None)
            if preset:
                self._step2.set_preset(preset)

    def _on_preset_selected(self, preset_id: str) -> None:
        self._config.app.preset = preset_id

    def _finish(self) -> None:
        """설정 수집 → 저장 → 완료."""
        # Step 1: 프리셋 적용
        pid = self._step1.selected_preset()
        self._config.app.preset = pid

        preset = next((p for p in PRESETS if p.id.value == pid), None)
        if preset:
            self._config.stt.model_name = preset.stt.model_id
            self._config.vad.model_name = preset.vad.model_id
            # GGUF 모델은 경로 지정 필요 — 여기서는 모델 ID만 기록
            if preset.translator.source == "huggingface":
                self._config.translator.model_path = preset.translator.model_id

        # Step 3: 언어 설정
        self._config.stt.language = self._step3.source_language()
        self._config.translator.target_language = self._step3.target_language()

        # first_run 해제
        self._config.app.first_run = False

        save_config(self._config)
        self.wizard_completed.emit(self._config)
        self.accept()


class _StepIndicator(QWidget):
    """상단 스텝 인디케이터 (Step 1 — 2 — 3 — 4)."""

    def __init__(self, total: int, parent=None) -> None:
        super().__init__(parent)
        self._total = total
        self._current = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(0)

        self._labels: list[QLabel] = []
        for i in range(total):
            lbl = QLabel(f"Step {i + 1}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._labels.append(lbl)
            layout.addWidget(lbl)

            if i < total - 1:
                sep = QLabel("→")
                sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sep.setStyleSheet("color: gray;")
                layout.addWidget(sep)

        self._refresh()

    def set_step(self, step: int) -> None:
        self._current = step
        self._refresh()

    def _refresh(self) -> None:
        for i, lbl in enumerate(self._labels):
            if i == self._current:
                lbl.setStyleSheet("font-weight: bold; color: #0078D4;")
            elif i < self._current:
                lbl.setStyleSheet("color: #228822;")
            else:
                lbl.setStyleSheet("color: gray;")
