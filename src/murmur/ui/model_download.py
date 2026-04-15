"""모델 다운로드 공용 위젯.

초기 설정 마법사(Step 2)와 설정창 [모델] 탭에서 동일한 UI/스레드를 재사용한다.
HuggingFace 모델만 자동 다운로드하며, GGUF는 수동 경로 안내, builtin은 런타임 자동 로드.
"""
from __future__ import annotations

import os
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def estimate_repo_size(repo_id: str) -> int:
    """HF 리포지토리의 총 파일 크기(바이트)를 추정한다. 실패 시 0."""
    try:
        from huggingface_hub import HfApi  # type: ignore[import-untyped]
        api = HfApi()
        info = api.model_info(repo_id, files_metadata=True)
        return sum(
            (getattr(f, "size", None) or 0) for f in (info.siblings or [])
        )
    except Exception:
        return 0


class ModelDownloadThread(QThread):
    """단일 모델 다운로드 진행상황을 emit한다."""

    progress = Signal(int, str)   # percent (-1이면 indeterminate), message
    finished = Signal(bool, str)  # success, message

    def __init__(self, model_id: str, source: str, parent=None) -> None:
        super().__init__(parent)
        self._model_id = model_id
        self._source = source
        self._done = threading.Event()
        self._total_bytes = 0

    def run(self) -> None:
        try:
            if self._source == "huggingface":
                self._download_hf()
            else:
                self.finished.emit(
                    False,
                    f"GGUF 모델은 수동으로 다운로드 후 설정에서 경로를 지정하세요.\n"
                    f"모델 ID: {self._model_id}",
                )
        except Exception as e:
            self._done.set()
            self.finished.emit(False, str(e))

    def _download_hf(self) -> None:
        from huggingface_hub import snapshot_download  # type: ignore[import-untyped]

        from murmur.config import MODELS_DIR

        cache_root = MODELS_DIR / "hub"
        cache_root.mkdir(parents=True, exist_ok=True)

        self.progress.emit(0, "모델 크기 확인 중...")
        self._total_bytes = estimate_repo_size(self._model_id)

        poller = threading.Thread(
            target=self._poll_progress,
            args=(cache_root,),
            daemon=True,
        )
        poller.start()

        try:
            snapshot_download(
                repo_id=self._model_id,
                cache_dir=str(cache_root),
                local_files_only=False,
            )
        finally:
            self._done.set()
            poller.join(timeout=2.0)

        self.progress.emit(100, "다운로드 완료")
        self.finished.emit(True, "")

    def _poll_progress(self, cache_root) -> None:
        repo_dir_name = "models--" + self._model_id.replace("/", "--")
        target = cache_root / repo_dir_name

        while not self._done.wait(1.0):
            size_bytes = 0
            if target.exists():
                for root, _dirs, files in os.walk(target, followlinks=False):
                    for f in files:
                        try:
                            size_bytes += os.path.getsize(os.path.join(root, f))
                        except OSError:
                            pass

            mb = size_bytes / (1024 * 1024)
            if self._total_bytes > 0:
                pct = min(99, int(size_bytes / self._total_bytes * 100))
                total_mb = self._total_bytes / (1024 * 1024)
                self.progress.emit(
                    pct, f"다운로드 중... {mb:.1f} / {total_mb:.1f} MB"
                )
            else:
                self.progress.emit(-1, f"다운로드 중... {mb:.1f} MB")


class DownloadRow(QWidget):
    """개별 모델 다운로드 행 — 이름/크기/상태/버튼/진행바."""

    def __init__(
        self,
        name: str,
        model_id: str,
        size_mb: int,
        source: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._model_id = model_id
        self._source = source
        self._thread: ModelDownloadThread | None = None
        self._setup_ui(name, size_mb, source)

    def _setup_ui(self, name: str, size_mb: int, source: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)

        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)

        name_lbl = QLabel(f"<b>{name}</b>")
        size_lbl = QLabel(f"[{size_mb:,} MB]")
        size_lbl.setStyleSheet("color: gray; font-size: 11px;")

        self._status_lbl = QLabel()
        btn_label = {
            "huggingface": "다운로드",
            "gguf": "경로 안내",
            "builtin": "자동 설치",
        }.get(source, "다운로드")
        self._btn = QPushButton(btn_label)
        self._btn.setFixedWidth(90)
        self._btn.clicked.connect(self._on_download)

        top_layout.addWidget(name_lbl)
        top_layout.addWidget(size_lbl)
        top_layout.addStretch()
        top_layout.addWidget(self._status_lbl)
        top_layout.addWidget(self._btn)
        layout.addWidget(top)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._msg_lbl = QLabel()
        self._msg_lbl.setWordWrap(True)
        self._msg_lbl.setStyleSheet("font-size: 11px; color: gray;")
        self._msg_lbl.setVisible(False)
        layout.addWidget(self._msg_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ddd;")
        layout.addWidget(sep)

        self._check_cached()

    def _check_cached(self) -> None:
        if self._source == "builtin":
            self._status_lbl.setText("자동 설치")
            self._status_lbl.setStyleSheet("color: #228822;")
            self._btn.setEnabled(False)
            return
        if self._source == "huggingface":
            try:
                from huggingface_hub import try_to_load_from_cache  # type: ignore[import-untyped]

                from murmur.config import MODELS_DIR
                result = try_to_load_from_cache(
                    repo_id=self._model_id,
                    filename="config.json",
                    cache_dir=str(MODELS_DIR / "hub"),
                )
                if result is not None:
                    self._set_ready()
                    return
            except Exception:
                pass
        self._status_lbl.setText("미설치")
        self._status_lbl.setStyleSheet("color: #CC4400;")

    def _set_ready(self) -> None:
        self._status_lbl.setText("준비됨 ✓")
        self._status_lbl.setStyleSheet("color: #228822;")
        self._btn.setEnabled(False)
        self._btn.setText("완료")

    def _on_download(self) -> None:
        if self._source != "huggingface":
            self._msg_lbl.setText(
                f"Hugging Face에서 GGUF 파일을 직접 다운로드하세요:\n"
                f"https://huggingface.co/{self._model_id}\n"
                f"다운로드 후 설정 → 모델 탭에서 경로를 지정하세요."
            )
            self._msg_lbl.setVisible(True)
            return

        self._btn.setEnabled(False)
        self._btn.setText("다운로드 중")
        self._progress.setVisible(True)
        self._progress.setValue(0)

        self._thread = ModelDownloadThread(self._model_id, self._source, self)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_finished)
        self._thread.start()

    def _on_progress(self, pct: int, msg: str) -> None:
        if pct < 0:
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(pct)
        self._status_lbl.setText(msg)

    def _on_finished(self, success: bool, msg: str) -> None:
        self._progress.setVisible(False)
        if success:
            self._set_ready()
        else:
            self._btn.setEnabled(True)
            self._btn.setText("재시도")
            self._msg_lbl.setText(msg)
            self._msg_lbl.setVisible(True)
            self._status_lbl.setText("실패")
            self._status_lbl.setStyleSheet("color: red;")
