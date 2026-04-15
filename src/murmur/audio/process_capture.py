"""프로세스 단위 오디오 캡처 — Windows Process Loopback API (ActivateAudioInterfaceAsync).

참고: Microsoft Windows-classic-samples/ApplicationLoopback.
요구 사항: Windows 10 build 19041 (2004) 이상.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import POINTER, Structure, Union, byref, c_ubyte, c_uint32, c_ushort
from ctypes import wintypes as wt
from multiprocessing import Queue

import numpy as np
from comtypes import COMMETHOD, GUID, IUnknown
from comtypes.hresult import S_OK

from murmur.audio.capture import BaseCapture, _resample, _to_mono
from murmur.config import AudioConfig

logger = logging.getLogger(__name__)

# --- 상수 --------------------------------------------------------------------

VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000

AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0

VT_BLOB = 65

WAVE_FORMAT_PCM = 1
REFTIMES_PER_SEC = 10_000_000  # 100ns

WAIT_OBJECT_0 = 0
INFINITE = 0xFFFFFFFF

AUDCLNT_BUFFERFLAGS_SILENT = 0x2

# 내부 캡처 포맷 — 16kHz 모노로 리샘플하기 전 중간 포맷.
CAPTURE_SAMPLE_RATE = 48000
CAPTURE_CHANNELS = 2
CAPTURE_BITS = 16
CAPTURE_BUFFER_DURATION = 2 * REFTIMES_PER_SEC // 10  # 200ms

# --- 구조체 ------------------------------------------------------------------


class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(Structure):
    _fields_ = [
        ("TargetProcessId", wt.DWORD),
        ("ProcessLoopbackMode", wt.DWORD),
    ]


class AUDIOCLIENT_ACTIVATION_PARAMS(Structure):
    _fields_ = [
        ("ActivationType", wt.DWORD),
        ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


class WAVEFORMATEX(Structure):
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", c_ushort),
        ("nChannels", c_ushort),
        ("nSamplesPerSec", wt.DWORD),
        ("nAvgBytesPerSec", wt.DWORD),
        ("nBlockAlign", c_ushort),
        ("wBitsPerSample", c_ushort),
        ("cbSize", c_ushort),
    ]


class BLOB(Structure):
    _fields_ = [("cbSize", wt.DWORD), ("pBlobData", POINTER(c_ubyte))]


class _PropVariantUnion(Union):
    _fields_ = [
        ("blob", BLOB),
        ("_pad", ctypes.c_ulonglong * 2),
    ]


class PROPVARIANT(Structure):
    _fields_ = [
        ("vt", c_ushort),
        ("wReserved1", c_ushort),
        ("wReserved2", c_ushort),
        ("wReserved3", c_ushort),
        ("u", _PropVariantUnion),
    ]


# --- COM 인터페이스 ---------------------------------------------------------

IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
IID_IActivateAudioInterfaceCompletionHandler = GUID(
    "{41D949AB-9862-444A-80F6-C261334DA5EB}"
)
IID_IActivateAudioInterfaceAsyncOperation = GUID(
    "{72A22D78-CDE4-431D-B8CC-843A71199B6D}"
)
IID_IAgileObject = GUID("{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}")


class IAgileObject(IUnknown):
    """마커 인터페이스 — 객체가 apartment-neutral임을 선언."""
    _iid_ = IID_IAgileObject
    _methods_ = []


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceAsyncOperation
    _methods_ = [
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetActivateResult",
            (["out"], POINTER(ctypes.HRESULT), "activateResult"),
            (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
        ),
    ]


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceCompletionHandler
    _methods_ = [
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "ActivateCompleted",
            (["in"], POINTER(IActivateAudioInterfaceAsyncOperation), "op"),
        ),
    ]


class IAudioClient(IUnknown):
    _iid_ = IID_IAudioClient
    _methods_ = [
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "Initialize",
            (["in"], wt.DWORD, "ShareMode"),
            (["in"], wt.DWORD, "StreamFlags"),
            (["in"], ctypes.c_longlong, "hnsBufferDuration"),
            (["in"], ctypes.c_longlong, "hnsPeriodicity"),
            (["in"], POINTER(WAVEFORMATEX), "pFormat"),
            (["in"], POINTER(GUID), "AudioSessionGuid"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetBufferSize",
            (["out"], POINTER(wt.UINT), "pNumBufferFrames"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetStreamLatency",
            (["out"], POINTER(ctypes.c_longlong), "phnsLatency"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetCurrentPadding",
            (["out"], POINTER(wt.UINT), "pNumPaddingFrames"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "IsFormatSupported",
            (["in"], wt.DWORD, "ShareMode"),
            (["in"], POINTER(WAVEFORMATEX), "pFormat"),
            (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppClosestMatch"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetMixFormat",
            (["out"], POINTER(POINTER(WAVEFORMATEX)), "ppDeviceFormat"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetDevicePeriod",
            (["out"], POINTER(ctypes.c_longlong), "phnsDefaultDevicePeriod"),
            (["out"], POINTER(ctypes.c_longlong), "phnsMinimumDevicePeriod"),
        ),
        COMMETHOD([], ctypes.HRESULT, "Start"),
        COMMETHOD([], ctypes.HRESULT, "Stop"),
        COMMETHOD([], ctypes.HRESULT, "Reset"),
        COMMETHOD(
            [], ctypes.HRESULT, "SetEventHandle", (["in"], wt.HANDLE, "eventHandle")
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetService",
            (["in"], POINTER(GUID), "riid"),
            (["out"], POINTER(ctypes.c_void_p), "ppv"),
        ),
    ]


class IAudioCaptureClient(IUnknown):
    _iid_ = IID_IAudioCaptureClient
    _methods_ = [
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetBuffer",
            (["out"], POINTER(POINTER(c_ubyte)), "ppData"),
            (["out"], POINTER(wt.UINT), "pNumFramesToRead"),
            (["out"], POINTER(wt.DWORD), "pdwFlags"),
            (["out"], POINTER(ctypes.c_ulonglong), "pu64DevicePosition"),
            (["out"], POINTER(ctypes.c_ulonglong), "pu64QPCPosition"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "ReleaseBuffer",
            (["in"], wt.UINT, "NumFramesRead"),
        ),
        COMMETHOD(
            [],
            ctypes.HRESULT,
            "GetNextPacketSize",
            (["out"], POINTER(wt.UINT), "pNumFramesInNextPacket"),
        ),
    ]


# --- Win32 API ---------------------------------------------------------------

_ole32 = ctypes.windll.ole32
_kernel32 = ctypes.windll.kernel32
_mmdevapi = ctypes.windll.mmdevapi

_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wt.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoUninitialize.argtypes = []

_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
_kernel32.CreateEventW.restype = wt.HANDLE
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_kernel32.CloseHandle.restype = wt.BOOL
_kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_kernel32.WaitForSingleObject.restype = wt.DWORD

_mmdevapi.ActivateAudioInterfaceAsync.argtypes = [
    wt.LPCWSTR,
    POINTER(GUID),
    POINTER(PROPVARIANT),
    ctypes.c_void_p,  # IActivateAudioInterfaceCompletionHandler*
    POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
]
_mmdevapi.ActivateAudioInterfaceAsync.restype = ctypes.c_long

COINIT_MULTITHREADED = 0x0


# --- 완료 핸들러 ------------------------------------------------------------

from comtypes import COMObject  # noqa: E402


class _CompletionHandler(COMObject):
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler, IAgileObject]

    def __init__(self) -> None:
        super().__init__()
        self.event = threading.Event()

    def IActivateAudioInterfaceCompletionHandler_ActivateCompleted(self, op):  # noqa: N802
        self.event.set()
        return S_OK


# --- 캡처 구현 --------------------------------------------------------------


def _build_format() -> WAVEFORMATEX:
    fmt = WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_PCM
    fmt.nChannels = CAPTURE_CHANNELS
    fmt.nSamplesPerSec = CAPTURE_SAMPLE_RATE
    fmt.wBitsPerSample = CAPTURE_BITS
    fmt.nBlockAlign = fmt.nChannels * fmt.wBitsPerSample // 8
    fmt.nAvgBytesPerSec = fmt.nSamplesPerSec * fmt.nBlockAlign
    fmt.cbSize = 0
    return fmt


def _build_activation_propvariant(pid: int) -> tuple[PROPVARIANT, AUDIOCLIENT_ACTIVATION_PARAMS]:
    params = AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = (
        PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
    )

    pv = PROPVARIANT()
    pv.vt = VT_BLOB
    pv.u.blob.cbSize = ctypes.sizeof(AUDIOCLIENT_ACTIVATION_PARAMS)
    pv.u.blob.pBlobData = ctypes.cast(
        ctypes.pointer(params), POINTER(c_ubyte)
    )
    return pv, params  # params 살아있어야 pBlobData 유효


class ProcessLoopbackCapture(BaseCapture):
    """특정 프로세스(및 자식 프로세스 트리)의 오디오만 캡처한다."""

    def _capture_loop(self) -> None:
        _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)

        event_handle = None
        audio_client = None
        capture_client = None
        try:
            audio_client = self._activate_audio_client(self._config.target_app_pid)
            if audio_client is None:
                return

            fmt = _build_format()
            try:
                audio_client.Initialize(
                    AUDCLNT_SHAREMODE_SHARED,
                    AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK,
                    CAPTURE_BUFFER_DURATION,
                    0,
                    byref(fmt),
                    None,
                )
            except OSError as e:
                logger.error("IAudioClient::Initialize failed: %s", e)
                return

            event_handle = _kernel32.CreateEventW(None, False, False, None)
            if not event_handle:
                logger.error("CreateEventW failed")
                return
            audio_client.SetEventHandle(event_handle)

            service_void = audio_client.GetService(byref(IID_IAudioCaptureClient))
            capture_client = ctypes.cast(
                ctypes.c_void_p(service_void), POINTER(IAudioCaptureClient)
            )

            audio_client.Start()
            logger.info(
                "Process loopback capture started (pid=%d, %dHz %dch → %dHz mono)",
                self._config.target_app_pid,
                CAPTURE_SAMPLE_RATE,
                CAPTURE_CHANNELS,
                self._config.sample_rate,
            )

            self._capture_packets(capture_client, event_handle, fmt)

            audio_client.Stop()

        except Exception:
            logger.exception("Process loopback capture error")
        finally:
            if event_handle:
                _kernel32.CloseHandle(event_handle)
            try:
                _ole32.CoUninitialize()
            except OSError:
                pass

    def _activate_audio_client(self, pid: int) -> IAudioClient | None:
        handler = _CompletionHandler()
        pv, params_keepalive = _build_activation_propvariant(pid)
        _ = params_keepalive  # keep reference alive for duration of call

        op_ptr = ctypes.POINTER(IActivateAudioInterfaceAsyncOperation)()
        handler_com = handler.QueryInterface(
            IActivateAudioInterfaceCompletionHandler
        )
        handler_addr = ctypes.cast(handler_com, ctypes.c_void_p).value
        hr = _mmdevapi.ActivateAudioInterfaceAsync(
            VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
            byref(IID_IAudioClient),
            byref(pv),
            handler_addr,
            byref(op_ptr),
        )
        if hr != 0:
            logger.error("ActivateAudioInterfaceAsync hr=0x%08X", hr & 0xFFFFFFFF)
            return None

        if not handler.event.wait(timeout=5.0):
            logger.error("Activation did not complete within 5s")
            return None

        activate_hr, unknown_ptr = op_ptr.GetActivateResult()
        if activate_hr != S_OK or not unknown_ptr:
            logger.error(
                "GetActivateResult failed: 0x%08X (pid=%d may not be capturable)",
                activate_hr & 0xFFFFFFFF,
                pid,
            )
            return None

        return unknown_ptr.QueryInterface(IAudioClient)

    def _capture_packets(
        self,
        capture_client: IAudioCaptureClient,
        event_handle: int,
        fmt: WAVEFORMATEX,
    ) -> None:
        dst_rate = self._config.sample_rate
        src_rate = fmt.nSamplesPerSec
        channels = fmt.nChannels
        bytes_per_sample = fmt.wBitsPerSample // 8

        while self._running:
            wait = _kernel32.WaitForSingleObject(event_handle, 200)
            if wait != WAIT_OBJECT_0:
                continue

            num_next = capture_client.GetNextPacketSize()
            while num_next > 0:
                data_ptr, num_frames, flags, _dev_pos, _qpc_pos = (
                    capture_client.GetBuffer()
                )
                n = num_frames
                if n == 0:
                    capture_client.ReleaseBuffer(0)
                    num_next = capture_client.GetNextPacketSize()
                    continue

                byte_count = n * channels * bytes_per_sample
                if flags & AUDCLNT_BUFFERFLAGS_SILENT:
                    audio = np.zeros(n * channels, dtype=np.int16)
                else:
                    buf = ctypes.string_at(data_ptr, byte_count)
                    audio = np.frombuffer(buf, dtype=np.int16).copy()

                capture_client.ReleaseBuffer(n)

                audio_f = audio.astype(np.float32) / 32768.0
                audio_f = _to_mono(audio_f, channels)
                if src_rate != dst_rate:
                    audio_f = _resample(audio_f, src_rate, dst_rate)
                self._push(audio_f)

                num_next = capture_client.GetNextPacketSize()
