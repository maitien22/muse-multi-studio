@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (echo Hay cai Python 3.11+ & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install -r requirements-windows.txt pyinstaller
exit /b %errorlevel%
