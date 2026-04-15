import logging
import multiprocessing
import os
import sys
import traceback
from pathlib import Path


def _setup_logging() -> Path:
    """파일 로깅 설정. pythonw.exe 실행 시 stdout/stderr이 None이므로 파일만 사용.

    %APPDATA%/Murmur/murmur.log 로 기록한다.
    """
    app_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "Murmur"
    app_dir.mkdir(parents=True, exist_ok=True)
    log_path = app_dir / "murmur.log"

    # pythonw에서는 stdout/stderr이 None — 이를 참조하는 라이브러리가 있으면
    # 조용히 죽으므로 빈 파일로 대체한다.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(log_path, "a", encoding="utf-8", buffering=1)

    logging.basicConfig(
        filename=str(log_path),
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s [%(process)d %(name)s] %(levelname)s: %(message)s",
        encoding="utf-8",
    )
    return log_path


def _setup_hf_cache() -> None:
    """HuggingFace 모델 캐시 경로를 %APPDATA%/Murmur/models/로 고정한다.

    `huggingface_hub`가 처음 import되기 전에 환경변수를 설정해야 유효하다.
    """
    from murmur.config import MODELS_DIR
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(MODELS_DIR))
    os.environ.setdefault("HF_HUB_CACHE", str(MODELS_DIR / "hub"))


def main():
    multiprocessing.freeze_support()
    log_path = _setup_logging()
    _setup_hf_cache()
    logging.info("Murmur launching (log: %s)", log_path)

    try:
        from murmur.app import MurmurApp
        app = MurmurApp()
        sys.exit(app.run())
    except SystemExit:
        raise
    except BaseException:
        logging.exception("Fatal error during startup")
        # 파일로도 전체 트레이스 기록 (logging 실패 대비)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n=== fatal error ===\n")
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
