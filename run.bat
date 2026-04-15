@echo off
REM Murmur 앱 실행 배치 (GUI 모드 — 콘솔 숨김)
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m murmur %*
