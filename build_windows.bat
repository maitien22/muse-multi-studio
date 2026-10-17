@echo off
setlocal
cd /d "%~dp0"
call start_build_requirements.bat
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name MuseMultiStudio --collect-all webview --collect-all uvicorn --add-data "app\static;app\static" launch.py
if errorlevel 1 (
  echo LOI: Build EXE khong thanh cong.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\smoke_windows.ps1" -ExePath "dist\MuseMultiStudio\MuseMultiStudio.exe"
if errorlevel 1 (
  echo LOI: EXE da tao nhung khong vuot qua smoke test.
  pause
  exit /b 1
)
if exist "dist\MuseMultiStudio-Windows-v0.2.0.zip" del /q "dist\MuseMultiStudio-Windows-v0.2.0.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\MuseMultiStudio' -DestinationPath 'dist\MuseMultiStudio-Windows-v0.2.0.zip' -Force"
if errorlevel 1 exit /b 1
echo THANH CONG: dist\MuseMultiStudio-Windows-v0.2.0.zip
echo Chay dist\MuseMultiStudio\MuseMultiStudio.exe hoac giai nen ZIP.
pause
