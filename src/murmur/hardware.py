"""PC 사양 자동 감지 모듈.

GPU(VRAM), RAM, CPU 정보를 읽어 HardwareInfo를 반환한다.
- GPU: torch.cuda (이미 의존성으로 포함됨)
- RAM: ctypes.windll (Windows 전용, 다른 플랫폼은 0 반환)
- CPU: platform.processor()
"""
from __future__ import annotations

import ctypes
import platform
import struct
from dataclasses import dataclass


@dataclass
class HardwareInfo:
    gpu_name: str        # "NVIDIA GeForce RTX 3060" 또는 "없음"
    vram_gb: float       # GB 단위 (0.0이면 GPU 없음/불명)
    ram_gb: float        # GB 단위
    cpu_name: str        # CPU 모델명
    has_cuda: bool       # CUDA 사용 가능 여부

    def summary(self) -> str:
        lines = [
            f"GPU: {self.gpu_name}" + (f" ({self.vram_gb:.0f}GB VRAM)" if self.vram_gb else ""),
            f"RAM: {self.ram_gb:.0f}GB",
            f"CPU: {self.cpu_name}",
        ]
        return "\n".join(lines)


def detect_hardware() -> HardwareInfo:
    """현재 PC의 하드웨어 정보를 수집하여 반환한다."""
    gpu_name, vram_gb, has_cuda = _detect_gpu()
    ram_gb = _detect_ram()
    cpu_name = _detect_cpu()
    return HardwareInfo(
        gpu_name=gpu_name,
        vram_gb=vram_gb,
        ram_gb=ram_gb,
        cpu_name=cpu_name,
        has_cuda=has_cuda,
    )


def _detect_gpu() -> tuple[str, float, bool]:
    """(gpu_name, vram_gb, has_cuda) 반환."""
    try:
        import torch

        if not torch.cuda.is_available():
            return "없음 (CPU 전용)", 0.0, False

        props = torch.cuda.get_device_properties(0)
        name = props.name
        vram_bytes = props.total_memory
        vram_gb = vram_bytes / (1024 ** 3)
        return name, round(vram_gb, 1), True
    except Exception:
        return "감지 실패", 0.0, False


def _detect_ram() -> float:
    """시스템 RAM 용량을 GB 단위로 반환한다."""
    if platform.system() != "Windows":
        return _detect_ram_fallback()

    try:
        # MEMORYSTATUSEX 구조체 (64바이트)
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return round(stat.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        return _detect_ram_fallback()


def _detect_ram_fallback() -> float:
    """psutil이 있으면 사용, 없으면 0 반환."""
    try:
        import psutil  # type: ignore[import-untyped]
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        return 0.0


def _detect_cpu() -> str:
    name = platform.processor()
    if not name:
        # Windows에서 platform.processor()가 빈 문자열을 반환하는 경우
        try:
            import subprocess
            result = subprocess.run(
                ["wmic", "cpu", "get", "name", "/value"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Name="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
        return "알 수 없음"
    return name
