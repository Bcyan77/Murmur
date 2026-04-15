"""모델 프리셋 정의 및 권장 로직."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from murmur.hardware import HardwareInfo


class PresetID(str, Enum):
    LOW_SPEC = "low_spec"
    KOREAN_OPTIMIZED = "korean_optimized"
    MULTILANG = "multilang"
    BEST_QUALITY = "best_quality"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ModelSpec:
    """다운로드/로딩에 필요한 모델 메타데이터."""
    name: str           # 사람이 읽을 수 있는 이름
    model_id: str       # HuggingFace hub ID 또는 내부 식별자
    size_mb: int        # 대략적인 다운로드 크기 (MB)
    source: str         # "huggingface" | "gguf" | "builtin"
    is_optional: bool = False


@dataclass(frozen=True)
class Preset:
    id: PresetID
    name: str
    description: str
    required_vram_gb: float    # 동시 로딩 기준 최소 VRAM
    requires_cuda: bool
    stt: ModelSpec
    translator: ModelSpec
    vad: ModelSpec
    quality_stars: int          # 1~5


# ── 모델 스펙 정의 ─────────────────────────────────────────────────────────────

_SENSE_VOICE = ModelSpec(
    name="SenseVoice-Small",
    model_id="FunAudioLLM/SenseVoiceSmall",
    size_mb=234,
    source="huggingface",
)
_WHISPER_TURBO = ModelSpec(
    name="Whisper large-v3-turbo",
    model_id="openai/whisper-large-v3-turbo",
    size_mb=1600,
    source="huggingface",
)
_CANARY_QWEN = ModelSpec(
    name="Canary-Qwen 2.5B",
    model_id="nvidia/canary-qwen-2.5b",
    size_mb=5000,
    source="huggingface",
)

_NLLB_600M = ModelSpec(
    name="NLLB-200 600M",
    model_id="facebook/nllb-200-distilled-600M",
    size_mb=1200,
    source="huggingface",
)
_NLLB_3B = ModelSpec(
    name="NLLB-200 3.3B",
    model_id="facebook/nllb-200-3.3B",
    size_mb=6600,
    source="huggingface",
)
_AYA_23_8B_Q4 = ModelSpec(
    name="Aya 23-8B (GGUF Q4)",
    model_id="bartowski/aya-23-8B-GGUF",
    size_mb=4700,
    source="gguf",
)
_QWEN3_4B = ModelSpec(
    name="Qwen3-4B (GGUF Q4)",
    model_id="bartowski/Qwen3-4B-GGUF",
    size_mb=2600,
    source="gguf",
)

_FSMN_VAD = ModelSpec(
    name="fsmn-vad",
    model_id="fsmn-vad",
    size_mb=36,
    source="builtin",  # funasr가 SenseVoice 로드 시 자동 설치
)
_SILERO_VAD = ModelSpec(
    name="Silero VAD",
    model_id="snakers4/silero-vad",
    size_mb=2,
    source="builtin",  # torch.hub/pip로 첫 실행 시 자동 로드
)


# 모든 ModelSpec을 model_id로 조회할 수 있는 레지스트리.
# 커스텀 프리셋에서 개별 선택된 모델의 메타데이터를 찾을 때 사용.
ALL_MODELS: dict[str, ModelSpec] = {
    spec.model_id: spec
    for spec in (
        _SENSE_VOICE,
        _WHISPER_TURBO,
        _CANARY_QWEN,
        _NLLB_600M,
        _NLLB_3B,
        _AYA_23_8B_Q4,
        _QWEN3_4B,
        _FSMN_VAD,
        _SILERO_VAD,
    )
}


# ── 프리셋 목록 ────────────────────────────────────────────────────────────────

PRESETS: list[Preset] = [
    Preset(
        id=PresetID.LOW_SPEC,
        name="저사양 (CPU 전용)",
        description="GPU 없이 CPU만으로 실행. 속도가 느리지만 저사양 PC에서도 동작.",
        required_vram_gb=0.0,
        requires_cuda=False,
        stt=_SENSE_VOICE,
        translator=_NLLB_600M,
        vad=_FSMN_VAD,
        quality_stars=2,
    ),
    Preset(
        id=PresetID.KOREAN_OPTIMIZED,
        name="한국어 최적화",
        description="영어/일본어/중국어 → 한국어 번역에 최적화. SenseVoice + Aya 23-8B.",
        required_vram_gb=10.0,
        requires_cuda=True,
        stt=_SENSE_VOICE,
        translator=_AYA_23_8B_Q4,
        vad=_FSMN_VAD,
        quality_stars=4,
    ),
    Preset(
        id=PresetID.MULTILANG,
        name="다국어 범용",
        description="99개 언어 지원. Whisper + NLLB-200 3.3B. 넓은 언어 커버리지.",
        required_vram_gb=10.0,
        requires_cuda=True,
        stt=_WHISPER_TURBO,
        translator=_NLLB_3B,
        vad=_SILERO_VAD,
        quality_stars=3,
    ),
    Preset(
        id=PresetID.BEST_QUALITY,
        name="최고 정확도",
        description="최상위 STT + LLM 번역. 16GB VRAM 이상 필요.",
        required_vram_gb=16.0,
        requires_cuda=True,
        stt=_CANARY_QWEN,
        translator=_QWEN3_4B,
        vad=_SILERO_VAD,
        quality_stars=5,
    ),
]

PRESET_MAP: dict[str, Preset] = {p.id.value: p for p in PRESETS}


def get_preset(preset_id: str) -> Preset | None:
    return PRESET_MAP.get(preset_id)


def recommend_preset(hw: HardwareInfo) -> PresetID:
    """하드웨어 정보를 기반으로 최적 프리셋을 권장한다."""
    if not hw.has_cuda:
        return PresetID.LOW_SPEC

    vram = hw.vram_gb
    if vram >= 16.0:
        return PresetID.BEST_QUALITY
    if vram >= 10.0:
        return PresetID.KOREAN_OPTIMIZED
    if vram >= 6.0:
        # 6~10GB: NLLB-600M CPU 폴백으로 한국어 최적화 가능하지만 속도 저하
        return PresetID.KOREAN_OPTIMIZED
    # VRAM < 6GB: CPU 폴백 권장
    return PresetID.LOW_SPEC


def is_preset_runnable(preset: Preset, hw: HardwareInfo) -> tuple[bool, str]:
    """프리셋이 현재 HW에서 실행 가능한지 여부와 이유를 반환한다."""
    if preset.requires_cuda and not hw.has_cuda:
        return False, "CUDA 지원 GPU가 필요합니다"
    if preset.requires_cuda and hw.vram_gb < preset.required_vram_gb:
        reason = (
            f"VRAM {hw.vram_gb:.0f}GB — "
            f"{preset.required_vram_gb:.0f}GB 이상 필요"
        )
        return False, reason
    return True, ""
