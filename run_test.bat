@echo off
REM 테스트 스크립트 실행 배치 — 사용법: run_test.bat [capture|stt|realtime_stt|translator|pipeline]
cd /d "%~dp0"
call .venv\Scripts\activate.bat

if "%~1"=="" (
    echo.
    echo 사용법: run_test.bat [테스트명]
    echo.
    echo 가능한 테스트:
    echo   capture       - 5초간 시스템 오디오 캡처
    echo   stt           - WAV 파일 STT
    echo   realtime_stt  - 실시간 STT
    echo   translator    - 번역
    echo   pipeline      - 전체 파이프라인
    echo.
    pause
    exit /b 1
)

python tests\test_%1.py %2 %3 %4 %5
pause
