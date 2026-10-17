@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Vui long cai Python 3.11+ va bat Python Launcher.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install -r requirements-windows.txt
if errorlevel 1 (
    echo Khong the cai thu vien; kiem tra mang.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" run.py
if errorlevel 1 pause
