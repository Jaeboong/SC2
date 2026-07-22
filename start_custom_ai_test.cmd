@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Python virtual environment not found: .venv
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "app\play_custom_ai.py" --test
