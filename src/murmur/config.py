from __future__ import annotations

import os
import shutil
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

APP_DIR = Path(os.environ.get("APPDATA", "")) / "Murmur"
CONFIG_PATH = APP_DIR / "config.toml"
MODELS_DIR = APP_DIR / "models"
LOGS_DIR = APP_DIR / "logs"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config.default.toml"


@dataclass
class AppConfig:
    first_run: bool = True
    preset: str = "korean_optimized"
    websocket_enabled: bool = False
    websocket_port: int = 9090
    subtitle_log: bool = False
    log_level: str = "WARNING"
    hotkey_toggle: str = "ctrl+shift+m"
    hotkey_overlay: str = "ctrl+shift+o"
    hotkey_settings: str = "ctrl+shift+s"


@dataclass
class AudioConfig:
    sample_rate: int = 16000
    chunk_duration_ms: int = 30
    queue_maxsize: int = 100
    capture_mode: str = "system"   # "system" | "app"
    target_app_pid: int = 0


@dataclass
class VADConfig:
    model_name: str = "fsmn-vad"
    max_single_segment_time: int = 30000
    silence_duration_ms: int = 1500


@dataclass
class STTConfig:
    model_name: str = "FunAudioLLM/SenseVoiceSmall"
    device: str = "cuda:0"
    language: str = "auto"
    use_itn: bool = True
    batch_size_s: int = 60


@dataclass
class TranslatorConfig:
    model_path: str = ""
    target_language: str = "Korean"
    n_ctx: int = 2048
    n_gpu_layers: int = -1
    temperature: float = 0.1
    max_tokens: int = 256


@dataclass
class OverlayConfig:
    font_family: str = "Malgun Gothic"
    font_size: int = 24
    font_color: str = "#FFFFFF"
    bg_opacity: float = 0.8
    show_original: bool = True
    max_lines: int = 2
    position: str = "bottom-center"
    # 드래그로 이동했을 때 저장되는 좌표. position == "custom"일 때만 사용.
    custom_x: int = -1
    custom_y: int = -1


@dataclass
class MurmurConfig:
    app: AppConfig = field(default_factory=AppConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    translator: TranslatorConfig = field(default_factory=TranslatorConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)


def ensure_app_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def load_config(path: Path | None = None) -> MurmurConfig:
    config_path = path or CONFIG_PATH

    if not config_path.exists():
        ensure_app_dirs()
        if DEFAULT_CONFIG_PATH.exists():
            shutil.copy2(DEFAULT_CONFIG_PATH, config_path)
        else:
            config = MurmurConfig()
            save_config(config, config_path)
            return config

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        config = MurmurConfig()
        save_config(config, config_path)
        return config

    return _dict_to_config(data)


def save_config(config: MurmurConfig, path: Path | None = None) -> None:
    config_path = path or CONFIG_PATH
    ensure_app_dirs()
    data = asdict(config)
    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)


def _make(cls, data: dict):
    """dataclass를 안전하게 생성한다 — 알 수 없는 키는 무시한다."""
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


def _dict_to_config(data: dict) -> MurmurConfig:
    return MurmurConfig(
        app=_make(AppConfig, data.get("app", {})),
        audio=_make(AudioConfig, data.get("audio", {})),
        vad=_make(VADConfig, data.get("vad", {})),
        stt=_make(STTConfig, data.get("stt", {})),
        translator=_make(TranslatorConfig, data.get("translator", {})),
        overlay=_make(OverlayConfig, data.get("overlay", {})),
    )
