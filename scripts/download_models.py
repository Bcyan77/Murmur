"""번역 모델(Aya 23-8B GGUF Q4)을 HuggingFace에서 다운로드한다.

사용법:
    python scripts/download_models.py

다운로드 경로: %APPDATA%/Murmur/models/
"""

from huggingface_hub import hf_hub_download

from murmur.config import MODELS_DIR, ensure_app_dirs


# Aya 23 8B Q4 quantized GGUF
REPO_ID = "bartowski/aya-23-8B-GGUF"
FILENAME = "aya-23-8B-Q4_K_M.gguf"


def main():
    ensure_app_dirs()
    print(f"Downloading {FILENAME} to {MODELS_DIR}...")
    path = hf_hub_download(
        repo_id=REPO_ID,
        filename=FILENAME,
        local_dir=str(MODELS_DIR),
    )
    print(f"Downloaded: {path}")
    print(f"\nSet this path in your config.toml under [translator]:")
    print(f'model_path = "{path}"')


if __name__ == "__main__":
    main()
