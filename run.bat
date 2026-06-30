@echo off
REM ASCII-only batch (cmd reads .bat with system codepage, not UTF-8)
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo ============================================
echo   CardWirth KR Translation Editor
echo ============================================
echo Checking Python...
python --version
if errorlevel 1 (
  echo.
  echo [ERROR] python not found. Check Python install / PATH,
  echo         or run:  py -m app.server
  pause
  exit /b 1
)
echo Starting server... browser will open automatically.
echo To stop: press Ctrl+C in this window.
echo --------------------------------------------
python -m app.server
echo.
echo [server stopped] if there is an error above, please report it.
pause
