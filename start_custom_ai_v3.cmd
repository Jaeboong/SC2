@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" "app\play_custom_ai_v3.py"
) else (
  python "app\play_custom_ai_v3.py"
)
