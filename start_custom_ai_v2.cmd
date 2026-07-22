@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Python virtual environment not found: .venv
    pause
    exit /b 1
)
set "NODE_PATH=%~dp0tools\node_modules"
start "" ".venv\Scripts\pythonw.exe" "v2\app\play_custom_ai_v2.py"
