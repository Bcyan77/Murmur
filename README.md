# Murmur

실시간 시스템 오디오를 로컬에서 음성 인식·번역하여 투명 자막으로 표시하는 Windows 데스크톱 앱.

브라우저 영상, 미디어 플레이어, 게임 등 앱의 오디오를 캡처하여 번역 및 자막으로 출력합니다.

## 주요 기능

- **시스템 전체 / 앱 지정 오디오 캡처** — WASAPI Loopback 또는 Windows Process Loopback API(앱 단위, Windows 10 2004+ 필요)
- **로컬 STT + 번역 파이프라인** — SenseVoice-Small / Whisper / Canary, Aya 23-8B / NLLB 등 자유 조합
- **투명 오버레이 자막** — 클릭 투과, 항상 최상위, Alt+드래그로 위치 이동, 다중 모니터 지원
- **시스템 트레이 컨트롤** — 시작/정지, 오디오 소스 라이브 전환, 설정, 단축키
- **글로벌 단축키** — `Ctrl+Shift+M`(시작/정지), `Ctrl+Shift+O`(자막 표시), `Ctrl+Shift+S`(설정), 재바인딩 가능
- **모델 프리셋 시스템** — PC 사양 자동 감지 후 저사양/한국어 최적화/다국어/최고 정확도 추천
- **초기 설정 마법사** — 사양 감지 → 프리셋 선택 → 모델 다운로드 → 동작 테스트
- **번역 버퍼링** — 문장부호/시간 경계로 발화를 묶어 SOV 어순 문제 대응

## 스크린샷

_(준비 중)_

## 요구 사양

| 항목 | 최소 | 권장 |
|------|------|------|
| OS | Windows 10 (앱 지정 캡처는 2004/19041+) | Windows 11 |
| Python | 3.10 | 3.11–3.12 |
| GPU | 없음 (저사양 프리셋) | VRAM 10GB+ (한국어 최적화) |
| RAM | 8GB | 16GB+ |
| 디스크 | 모델에 따라 1–10GB |  |

## 설치

`uv`를 사용하여 의존성과 가상환경을 자동으로 관리합니다.

```bash
# 저장소 클론
git clone <repo-url> Murmur
cd Murmur

# 의존성 설치 (가상환경 자동 생성)
uv sync

# 번역(llama.cpp)까지 쓰려면
uv sync --extra translation
```

GPU로 STT/번역을 돌리려면 CUDA 빌드의 PyTorch와 `llama-cpp-python`이 필요합니다. 프리셋 선택 시 마법사가 안내합니다.

## 실행

```bash
# uv run으로 바로 실행 (가상환경 활성화 불필요)
uv run murmur

# 또는 모듈로
uv run python -m murmur

# 또는 배치(Windows)
run.bat
```

최초 실행 시 초기 설정 마법사가 자동으로 열립니다. 이후에는 시스템 트레이 아이콘으로 상주합니다.

### 트레이 메뉴

- **시작 / 정지** — 캡처 토글
- **오디오 소스** — "시스템 전체" 또는 현재 소리 내는 앱 중 하나 선택 (새로고침 포함)
- **자막 표시 / 숨김**
- **설정** — 4탭 설정 창
- **종료**

### 오버레이 조작

- 기본은 **클릭 투과** 상태로 영상 위에 표시됩니다
- `Alt` 키를 누른 상태에서 **좌클릭 드래그**로 자막 창을 이동할 수 있으며, 위치는 자동 저장됩니다
- 위치 프리셋(상/하 × 좌/중/우)은 설정 창에서 선택할 수 있습니다

## 설정

- 설정 파일: `%APPDATA%\Murmur\config.toml` (TOML)
- 모델 저장: `%APPDATA%\Murmur\models\`
- 자막 로그: `%APPDATA%\Murmur\logs\` (SRT 포맷, 옵션)

설정 창 탭:
- **오디오** — 캡처 모드, 원문/대상 언어
- **자막** — 글꼴, 크기, 색상, 배경 투명도, 위치, 원문 표시, 줄 수
- **모델** — 프리셋, STT/번역/VAD 모델 개별 선택
- **고급** — VAD 임계값, 번역 버퍼, GPU 디바이스, 단축키, 로그 레벨, WebSocket 출력

## 아키텍처

```
시스템 오디오 (WASAPI Loopback) / 앱별 오디오 (Process Loopback API)
  → 리샘플링 (16kHz 모노)
  → multiprocessing.Queue
  → VAD (에너지 기반 침묵 감지 + SenseVoice 내장 fsmn-vad)
  → STT (SenseVoice-Small / Whisper / Canary)
  → 번역 버퍼 (문장부호·타임아웃 기반 플러시)
  → 번역 (Aya 23-8B / NLLB)
  → 결과 Queue → Qt 시그널
  → PySide6 투명 오버레이
```

메인 프로세스는 UI·캡처를 담당하고 STT/번역은 별도 프로세스에서 동작합니다. Python GIL로 인한 CPU 모드 블로킹을 피하기 위한 설계입니다.

## 지원 모델

| 카테고리 | 모델 | 용도 |
|----------|------|------|
| STT | SenseVoice-Small | 한중일영 특화, 가장 빠름 (1순위) |
| STT | Whisper large-v3 Turbo | 99개 언어 범용 |
| STT | Canary-Qwen 2.5B | 최고 정확도, VRAM 16GB+ |
| 번역 | Aya 23-8B (GGUF Q4) | 고품질 한국어 (권장) |
| 번역 | NLLB-200 3.3B / 600M | 200개 언어, 경량 |
| 번역 | Qwen3-4B / Gemma3-4B | 문맥 번역 |
| VAD | fsmn-vad | SenseVoice 내장 |
| VAD | Silero VAD | 경량·정확 |

## 테스트

`tests/` 디렉토리의 스크립트는 독립 실행 방식입니다(pytest 아님).

```bash
python tests/test_capture.py           # 5초 시스템 오디오 캡처 → WAV
python tests/test_sessions.py          # 오디오 출력 중인 프로세스 목록
python tests/test_process_capture.py   # 특정 프로세스 오디오 캡처
python tests/test_stt.py               # WAV → 전사
python tests/test_realtime_stt.py      # 실시간 캡처 + 전사
python tests/test_translator.py        # 텍스트 → 번역
python tests/test_pipeline.py          # 전체 파이프라인 통합
```

`run_test.bat [테스트명]`으로도 실행할 수 있습니다.

## 라이선스

이 프로젝트는 **MIT** 라이선스를 따릅니다 ([LICENSE](LICENSE)).

외부 모델의 라이선스는 별도입니다.
- SenseVoice / Aya 23 / MADLAD-400: Apache 2.0
- Whisper: MIT
- NLLB: CC-BY-NC 4.0 (비상업 전용)

## 진행 상황

- ✅ Phase 1: 오디오 캡처 + STT 검증
- ✅ Phase 2: 번역 + 프로세스 분리
- ✅ Phase 3: PySide6 앱 프레임워크 + 투명 오버레이
- ✅ Phase 4: 설정·프리셋·초기 설정 마법사
- ✅ Phase 5: 앱 지정 캡처 + 오버레이 커스터마이징 + 단축키 + 스트리밍 최적화
- ⏳ Phase 6: 에러 처리·모델 핫스왑·자막 로그·패키징 (진행 예정)

자세한 체크리스트는 [TODO.md](TODO.md)에 있습니다.

## 참고 프로젝트

- [Hearsay](https://github.com/parkscloud/Hearsay) — WASAPI Loopback + faster-whisper 참고
- [Speech-Translate](https://github.com/Dadangdut33/Speech-Translate) — 투명 자막 오버레이 참고
- [WhisperLive](https://github.com/collabora/WhisperLive) / [WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) — 스트리밍 정책 참고
- [streaming-sensevoice](https://github.com/pengzhendong/streaming-sensevoice) — SenseVoice 스트리밍 참고
