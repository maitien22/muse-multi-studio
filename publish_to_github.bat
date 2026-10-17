@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
where git >nul 2>&1
if errorlevel 1 (
  echo Chua cai Git for Windows. Cai tu https://git-scm.com/downloads/win
  pause
  exit /b 1
)
echo ======================================================
echo MUSE MULTI STUDIO v0.2.0 - DAY SOURCE LEN GITHUB
 echo Tao repository PRIVATE muse-multi-studio TRONG tren GitHub truoc.
echo KHONG NHAP TOKEN HAY API KEY VAO CUA SO NAY.
echo ======================================================
set /p "REPO=Nhap URL repo (https://github.com/ten/muse-multi-studio.git): "
if "%REPO%"=="" exit /b 1
echo %REPO% | findstr /b /i /c:"https://github.com/" >nul
if errorlevel 1 (
  echo Chi chap nhan URL GitHub https://github.com/...
  pause
  exit /b 1
)
if not exist ".git" (
  git init -b main
  if errorlevel 1 goto fail
)
git add .
if errorlevel 1 goto fail
git diff --cached --quiet
if not errorlevel 1 goto push
git commit -m "Release Muse Multi Studio v0.2.0 - integrity fixes"
if errorlevel 1 (
  echo Thieu Git user.name/email? Cau hinh Git tren may truoc.
  goto fail
)
:push
git remote get-url origin >nul 2>&1
if errorlevel 1 (
  git remote add origin "%REPO%"
) else (
  for /f "delims=" %%R in ('git remote get-url origin') do set "EXISTING=%%R"
  if /i not "!EXISTING!"=="%REPO%" (
    echo Repository da cau hinh URL khac: !EXISTING!
    echo Dung lai de bao ve project; khong tu thay remote.
    goto fail
  )
)
git branch -M main
git push -u origin main
if errorlevel 1 goto fail
echo.
echo THANH CONG: Da push ma nguon. Vao GitHub ^> Actions ^> tai artifact Windows.
pause
exit /b 0
:fail
echo Co loi. KHONG duoc coi la da day ma nguon.
pause
exit /b 1
