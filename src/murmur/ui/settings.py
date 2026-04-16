from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from murmur.config import MurmurConfig, save_config

# 지원 언어 목록 (표시명 → 코드/값)
_STT_LANGUAGES = [
    ("자동 감지", "auto"),
    ("영어", "en"),
    ("일본어", "ja"),
    ("중국어", "zh"),
    ("한국어", "ko"),
    ("광둥어", "yue"),
]

_TARGET_LANGUAGES = [
    ("한국어", "Korean"),
    ("영어", "English"),
    ("일본어", "Japanese"),
    ("중국어", "Chinese"),
]

_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]

_POSITIONS = [
    ("하단 중앙", "bottom-center"),
    ("하단 좌측", "bottom-left"),
    ("하단 우측", "bottom-right"),
    ("상단 중앙", "top-center"),
    ("상단 좌측", "top-left"),
    ("상단 우측", "top-right"),
    ("사용자 지정 (드래그 위치)", "custom"),
]

_PRESETS = [
    ("저사양 (CPU 전용)", "low_spec"),
    ("한국어 최적화 (10GB VRAM)", "korean_optimized"),
    ("다국어 범용 (10GB VRAM)", "multilang"),
    ("최고 정확도 (16GB+ VRAM)", "best_quality"),
    ("커스텀", "custom"),
]

_STT_MODELS = [
    ("SenseVoice-Small", "FunAudioLLM/SenseVoiceSmall"),
    ("Whisper large-v3-turbo", "openai/whisper-large-v3-turbo"),
]

_TRANSLATOR_MODELS = [
    ("Aya 23-8B (Q4)", "bartowski/aya-23-8B-GGUF"),
    ("NLLB-200 3.3B", "facebook/nllb-200-3.3B"),
    ("NLLB-200 600M", "facebook/nllb-200-distilled-600M"),
    ("Qwen3-4B (Q4)", "Qwen/Qwen3-4B-GGUF"),
]

_VAD_MODELS = [
    ("fsmn-vad", "fsmn-vad"),
    ("Silero VAD", "silero-vad"),
]

# 프리셋별 모델 설정 (HF model_id 기준, presets.ALL_MODELS로 조회 가능)
_PRESET_MODELS: dict[str, dict] = {
    "low_spec": {
        "stt": "FunAudioLLM/SenseVoiceSmall",
        "translator": "facebook/nllb-200-distilled-600M",
        "vad": "fsmn-vad",
    },
    "korean_optimized": {
        "stt": "FunAudioLLM/SenseVoiceSmall",
        "translator": "bartowski/aya-23-8B-GGUF",
        "vad": "fsmn-vad",
    },
    "multilang": {
        "stt": "openai/whisper-large-v3-turbo",
        "translator": "facebook/nllb-200-3.3B",
        "vad": "snakers4/silero-vad",
    },
    "best_quality": {
        "stt": "FunAudioLLM/SenseVoiceSmall",
        "translator": "Qwen/Qwen3-4B-GGUF",
        "vad": "snakers4/silero-vad",
    },
}


class SettingsDialog(QDialog):
    """Murmur 설정 창 (오디오 / 자막 / 모델 / 고급 4탭)."""

    settings_applied = Signal(object)  # MurmurConfig

    def __init__(self, config: MurmurConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Murmur 설정")
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._config = copy.deepcopy(config)
        self._font_color = config.overlay.font_color
        self._preset_changing = False  # 프리셋 변경 중 개별 모델 시그널 차단용

        self._setup_ui()
        self._load_config()

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def get_config(self) -> MurmurConfig:
        return self._config

    # ── UI 구성 ────────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._make_audio_tab(), "오디오")
        self._tabs.addTab(self._make_subtitle_tab(), "자막")
        self._tabs.addTab(self._make_model_tab(), "모델")
        self._tabs.addTab(self._make_advanced_tab(), "고급")
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        apply_btn = buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply_btn.setText("적용")
        apply_btn.clicked.connect(self._on_apply)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── 오디오 탭 ──────────────────────────────────────────────────────────────

    def _make_audio_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # 캡처 모드
        self._capture_mode = QComboBox()
        self._capture_mode.addItem("시스템 전체 오디오", "system")
        self._capture_mode.addItem("특정 앱 지정 (트레이 메뉴에서 앱 선택)", "app")
        layout.addRow("캡처 모드:", self._capture_mode)

        # 원본 언어
        self._source_language = QComboBox()
        for label, code in _STT_LANGUAGES:
            self._source_language.addItem(label, code)
        layout.addRow("원본 언어:", self._source_language)

        # 자막 언어
        self._target_language = QComboBox()
        for label, code in _TARGET_LANGUAGES:
            self._target_language.addItem(label, code)
        layout.addRow("자막 언어:", self._target_language)

        return widget

    # ── 자막 탭 ────────────────────────────────────────────────────────────────

    def _make_subtitle_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # 글꼴 — QFontComboBox는 기본적으로 편집 가능 + 시스템 글꼴 자동완성
        self._font_family = QFontComboBox()
        self._font_family.setEditable(True)
        layout.addRow("글꼴:", self._font_family)

        # 글꼴 크기
        self._font_size = QSpinBox()
        self._font_size.setRange(10, 72)
        layout.addRow("글꼴 크기:", self._font_size)

        # 글꼴 색상
        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self._color_preview = QLabel()
        self._color_preview.setFixedSize(40, 24)
        self._color_preview.setAutoFillBackground(True)
        self._color_btn = QPushButton("선택...")
        self._color_btn.clicked.connect(self._pick_color)
        color_layout.addWidget(self._color_preview)
        color_layout.addWidget(self._color_btn)
        color_layout.addStretch()
        layout.addRow("글꼴 색상:", color_row)

        # 배경 투명도
        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        self._bg_opacity = QSlider(Qt.Orientation.Horizontal)
        self._bg_opacity.setRange(0, 100)
        self._opacity_label = QLabel("80%")
        self._bg_opacity.valueChanged.connect(
            lambda v: self._opacity_label.setText(f"{v}%")
        )
        opacity_layout.addWidget(self._bg_opacity)
        opacity_layout.addWidget(self._opacity_label)
        layout.addRow("배경 투명도:", opacity_row)

        # 위치
        self._position = QComboBox()
        for label, code in _POSITIONS:
            self._position.addItem(label, code)
        layout.addRow("기본 위치:", self._position)

        # 원문 표시
        self._show_original = QCheckBox("원문도 함께 표시")
        layout.addRow("", self._show_original)

        # 최대 줄 수
        self._max_lines = QSpinBox()
        self._max_lines.setRange(1, 6)
        layout.addRow("최대 줄 수:", self._max_lines)

        return widget

    # ── 모델 탭 ────────────────────────────────────────────────────────────────

    def _make_model_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        preset_group = QGroupBox("프리셋")
        preset_form = QFormLayout(preset_group)
        self._preset = QComboBox()
        for label, code in _PRESETS:
            self._preset.addItem(label, code)
        self._preset.currentIndexChanged.connect(self._on_preset_changed)
        preset_form.addRow("프리셋:", self._preset)
        layout.addWidget(preset_group)

        model_group = QGroupBox("개별 모델 설정")
        model_form = QFormLayout(model_group)

        self._stt_model = QComboBox()
        for label, code in _STT_MODELS:
            self._stt_model.addItem(label, code)
        self._stt_model.currentIndexChanged.connect(self._on_model_manual_change)
        model_form.addRow("STT 모델:", self._stt_model)

        self._translator_model = QComboBox()
        for label, code in _TRANSLATOR_MODELS:
            self._translator_model.addItem(label, code)
        self._translator_model.currentIndexChanged.connect(self._on_model_manual_change)
        model_form.addRow("번역 모델:", self._translator_model)

        self._vad_model = QComboBox()
        for label, code in _VAD_MODELS:
            self._vad_model.addItem(label, code)
        self._vad_model.currentIndexChanged.connect(self._on_model_manual_change)
        model_form.addRow("VAD:", self._vad_model)

        layout.addWidget(model_group)

        # 모델 다운로드 — 현재 프리셋 기준
        download_group = QGroupBox("모델 다운로드")
        self._download_layout = QVBoxLayout(download_group)
        self._download_rows: list = []
        self._refresh_download_rows()
        layout.addWidget(download_group)
        self._preset.currentIndexChanged.connect(self._refresh_download_rows)

        # 모델 저장 경로 열기
        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.addWidget(QLabel("모델 저장 경로:"))
        open_btn = QPushButton("폴더 열기")
        open_btn.setFixedWidth(100)
        open_btn.clicked.connect(self._open_models_dir)
        path_layout.addStretch()
        path_layout.addWidget(open_btn)
        layout.addWidget(path_row)

        note = QLabel(
            "※ 프리셋 변경 시 개별 모델이 자동으로 설정됩니다.\n"
            "※ 개별 모델 수동 변경 시 프리셋이 '커스텀'으로 전환됩니다."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(note)
        layout.addStretch()

        return widget

    # ── 고급 탭 ────────────────────────────────────────────────────────────────

    def _make_advanced_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # 무음 경계
        self._silence_duration = QDoubleSpinBox()
        self._silence_duration.setRange(0.3, 5.0)
        self._silence_duration.setSingleStep(0.1)
        self._silence_duration.setDecimals(1)
        self._silence_duration.setSuffix(" 초")
        layout.addRow("무음 경계:", self._silence_duration)

        # 번역 버퍼
        self._buffer_enabled = QCheckBox("활성화")
        layout.addRow("번역 버퍼 사용:", self._buffer_enabled)

        self._buffer_flush = QDoubleSpinBox()
        self._buffer_flush.setRange(0.2, 3.0)
        self._buffer_flush.setSingleStep(0.1)
        self._buffer_flush.setDecimals(1)
        self._buffer_flush.setSuffix(" 초")
        self._buffer_enabled.toggled.connect(self._buffer_flush.setEnabled)
        layout.addRow("번역 버퍼 타임아웃:", self._buffer_flush)

        # GPU 디바이스 — 감지된 CUDA 장치 목록을 동적으로 채움
        self._gpu_device = QComboBox()
        self._gpu_device.setEditable(True)
        self._populate_gpu_devices()
        layout.addRow("GPU 디바이스:", self._gpu_device)

        # WebSocket
        ws_row = QWidget()
        ws_layout = QHBoxLayout(ws_row)
        ws_layout.setContentsMargins(0, 0, 0, 0)
        self._ws_enabled = QCheckBox("활성화")
        self._ws_port = QSpinBox()
        self._ws_port.setRange(1024, 65535)
        self._ws_port.setPrefix("포트: ")
        self._ws_enabled.toggled.connect(self._ws_port.setEnabled)
        ws_layout.addWidget(self._ws_enabled)
        ws_layout.addWidget(self._ws_port)
        ws_layout.addStretch()
        layout.addRow("WebSocket 출력:", ws_row)

        # 자막 로그
        self._subtitle_log = QCheckBox("자막을 SRT 파일로 자동 저장")
        layout.addRow("자막 히스토리:", self._subtitle_log)

        # 로그 레벨
        self._log_level = QComboBox()
        for lvl in _LOG_LEVELS:
            self._log_level.addItem(lvl)
        layout.addRow("로그 레벨:", self._log_level)

        # 단축키
        self._hotkey_toggle = QLineEdit()
        self._hotkey_toggle.setPlaceholderText("ctrl+shift+m")
        layout.addRow("시작/정지 토글:", self._hotkey_toggle)

        self._hotkey_overlay = QLineEdit()
        self._hotkey_overlay.setPlaceholderText("ctrl+shift+o")
        layout.addRow("자막 표시/숨김:", self._hotkey_overlay)

        self._hotkey_settings = QLineEdit()
        self._hotkey_settings.setPlaceholderText("ctrl+shift+s")
        layout.addRow("설정 창 열기:", self._hotkey_settings)

        tradeoff = QLabel(
            "※ 무음 경계 / 버퍼 타임아웃을 줄이면 자막 지연이 짧아지지만, 천천히 "
            "말하거나 문장 중간에 멈추는 경우 자막이 끊겨 표시될 수 있습니다. "
            "짧은 조각을 개별 번역하면 한국어 어순 품질이 낮아질 수 있습니다."
        )
        tradeoff.setWordWrap(True)
        tradeoff.setStyleSheet("color: gray; font-size: 11px;")
        layout.addRow(tradeoff)

        return widget

    # ── 설정 로드/저장 ─────────────────────────────────────────────────────────

    def _populate_gpu_devices(self) -> None:
        """감지된 CUDA 장치를 콤보박스에 '인덱스 — 모델명' 형식으로 추가."""
        try:
            import torch
        except ImportError:
            torch = None  # type: ignore[assignment]

        if torch is not None and torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                dev_id = f"cuda:{i}"
                try:
                    name = torch.cuda.get_device_name(i)
                    label = f"{dev_id} — {name}"
                except Exception:
                    label = dev_id
                self._gpu_device.addItem(label, dev_id)
        else:
            # torch 없거나 CUDA 미지원 — 기본 항목만
            self._gpu_device.addItem("cuda:0", "cuda:0")
        self._gpu_device.addItem("cpu", "cpu")

    def _load_config(self) -> None:
        cfg = self._config

        # 오디오 탭
        _set_combo_by_data(self._capture_mode, cfg.audio.capture_mode)
        _set_combo_by_data(self._source_language, cfg.stt.language)
        _set_combo_by_data(self._target_language, cfg.translator.target_language)

        # 자막 탭
        self._font_family.setCurrentFont(QFont(cfg.overlay.font_family))
        self._font_size.setValue(cfg.overlay.font_size)
        self._font_color = cfg.overlay.font_color
        self._update_color_preview()
        self._bg_opacity.setValue(int(cfg.overlay.bg_opacity * 100))
        _set_combo_by_data(self._position, cfg.overlay.position)
        self._show_original.setChecked(cfg.overlay.show_original)
        self._max_lines.setValue(cfg.overlay.max_lines)

        # 모델 탭
        _set_combo_by_data(self._preset, cfg.app.preset)
        _set_combo_by_data(self._stt_model, cfg.stt.model_name)
        _set_combo_by_data(self._vad_model, cfg.vad.model_name)
        # translator model_path는 내부 ID 매핑 없으므로 첫 번째 항목 유지 (기본값)

        # 고급 탭
        self._silence_duration.setValue(cfg.vad.silence_duration_ms / 1000.0)
        self._buffer_enabled.setChecked(cfg.translator.buffer_enabled)
        self._buffer_flush.setValue(cfg.translator.buffer_flush_ms / 1000.0)
        self._buffer_flush.setEnabled(cfg.translator.buffer_enabled)
        if not _set_combo_by_data(self._gpu_device, cfg.stt.device):
            # 감지된 장치에 없으면 편집 가능 텍스트로 세팅
            self._gpu_device.setCurrentText(cfg.stt.device)
        self._ws_enabled.setChecked(cfg.app.websocket_enabled)
        self._ws_port.setValue(cfg.app.websocket_port)
        self._ws_port.setEnabled(cfg.app.websocket_enabled)
        self._subtitle_log.setChecked(cfg.app.subtitle_log)
        _set_combo_by_text(self._log_level, cfg.app.log_level)
        self._hotkey_toggle.setText(cfg.app.hotkey_toggle)
        self._hotkey_overlay.setText(cfg.app.hotkey_overlay)
        self._hotkey_settings.setText(cfg.app.hotkey_settings)

    def _collect_config(self) -> MurmurConfig:
        cfg = copy.deepcopy(self._config)

        # 오디오
        cfg.audio.capture_mode = self._capture_mode.currentData()
        cfg.stt.language = self._source_language.currentData()
        cfg.translator.target_language = self._target_language.currentData()

        # 자막
        cfg.overlay.font_family = (
            self._font_family.currentFont().family()
            or self._font_family.currentText().strip()
            or "Malgun Gothic"
        )
        cfg.overlay.font_size = self._font_size.value()
        cfg.overlay.font_color = self._font_color
        cfg.overlay.bg_opacity = self._bg_opacity.value() / 100.0
        cfg.overlay.position = self._position.currentData()
        cfg.overlay.show_original = self._show_original.isChecked()
        cfg.overlay.max_lines = self._max_lines.value()

        # 모델
        cfg.app.preset = self._preset.currentData()
        cfg.stt.model_name = self._stt_model.currentData()
        cfg.vad.model_name = self._vad_model.currentData()

        # 고급
        cfg.vad.silence_duration_ms = int(self._silence_duration.value() * 1000)
        cfg.translator.buffer_enabled = self._buffer_enabled.isChecked()
        cfg.translator.buffer_flush_ms = int(self._buffer_flush.value() * 1000)
        # itemData에 "cuda:0" 같은 식별자가 있으면 우선 사용, 없으면 편집된 텍스트
        device_data = self._gpu_device.currentData()
        if device_data:
            cfg.stt.device = device_data
        else:
            cfg.stt.device = self._gpu_device.currentText().strip()
        cfg.app.websocket_enabled = self._ws_enabled.isChecked()
        cfg.app.websocket_port = self._ws_port.value()
        cfg.app.subtitle_log = self._subtitle_log.isChecked()
        cfg.app.log_level = self._log_level.currentText()
        cfg.app.hotkey_toggle = self._hotkey_toggle.text().strip().lower()
        cfg.app.hotkey_overlay = self._hotkey_overlay.text().strip().lower()
        cfg.app.hotkey_settings = self._hotkey_settings.text().strip().lower()

        return cfg

    # ── 슬롯 ──────────────────────────────────────────────────────────────────

    def _on_apply(self) -> None:
        self._config = self._collect_config()
        save_config(self._config)
        self.settings_applied.emit(self._config)
        self.accept()

    def _refresh_download_rows(self) -> None:
        """현재 선택된 프리셋 기준으로 다운로드 행을 다시 구성한다.

        커스텀 프리셋인 경우 각 콤보박스(STT/번역/VAD)의 현재 선택 값을
        ALL_MODELS 레지스트리에서 찾아 행을 만든다.
        """
        from murmur.presets import ALL_MODELS, PRESETS
        from murmur.ui.model_download import DownloadRow

        # 이전 행과 addStretch 모두 제거 — deleteLater는 비동기이므로
        # 먼저 setParent(None)으로 화면에서 즉시 분리한다.
        while self._download_layout.count():
            item = self._download_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._download_rows.clear()

        preset_id = self._preset.currentData()
        if preset_id == "custom":
            ids = [
                self._stt_model.currentData(),
                self._translator_model.currentData(),
                self._vad_model.currentData(),
            ]
            specs = [ALL_MODELS[i] for i in ids if i in ALL_MODELS]
        else:
            preset = next((p for p in PRESETS if p.id.value == preset_id), None)
            if preset is None:
                return
            specs = [preset.stt, preset.translator, preset.vad]

        for spec in specs:
            row = DownloadRow(
                spec.name,
                spec.model_id,
                spec.size_mb,
                spec.source,
                gguf_filename=spec.gguf_filename,
            )
            row.downloaded.connect(self._on_gguf_downloaded)
            self._download_rows.append(row)
            self._download_layout.addWidget(row)
        self._download_layout.addStretch()

    def _on_gguf_downloaded(self, *args: str) -> None:
        """GGUF 번역 모델 다운로드 완료 시 config.translator.model_path 자동 설정.

        시그널 시그너처: (model_id, local_path). model_id는 여기서 사용하지 않음.
        """
        if len(args) >= 2:
            self._config.translator.model_path = args[1]

    def _open_models_dir(self) -> None:
        """탐색기에서 %APPDATA%/Murmur/models/ 폴더를 연다."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from murmur.config import MODELS_DIR
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(MODELS_DIR)))

    def _pick_color(self) -> None:
        initial = QColor(self._font_color)
        color = QColorDialog.getColor(initial, self, "글꼴 색상 선택")
        if color.isValid():
            self._font_color = color.name().upper()
            self._update_color_preview()

    def _update_color_preview(self) -> None:
        palette = self._color_preview.palette()
        palette.setColor(self._color_preview.backgroundRole(), QColor(self._font_color))
        self._color_preview.setPalette(palette)
        self._color_preview.setToolTip(self._font_color)

    def _on_preset_changed(self, index: int) -> None:
        preset_id = self._preset.itemData(index)
        if preset_id == "custom" or preset_id not in _PRESET_MODELS:
            return

        self._preset_changing = True
        models = _PRESET_MODELS[preset_id]
        _set_combo_by_data(self._stt_model, models["stt"])
        _set_combo_by_data(self._vad_model, models["vad"])
        # translator_model 콤보는 내부 ID 매핑으로 설정
        _set_combo_by_data(self._translator_model, models["translator"])
        self._preset_changing = False

    def _on_model_manual_change(self) -> None:
        if self._preset_changing:
            self._refresh_download_rows()
            return
        _set_combo_by_data(self._preset, "custom")
        self._refresh_download_rows()


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _set_combo_by_data(combo: QComboBox, data: str) -> bool:
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            combo.setCurrentIndex(i)
            return True
    return False


def _set_combo_by_text(combo: QComboBox, text: str) -> None:
    idx = combo.findText(text, Qt.MatchFlag.MatchFixedString)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    else:
        combo.setCurrentText(text)
