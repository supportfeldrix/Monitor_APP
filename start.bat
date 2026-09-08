@echo off
chcp 65001 >nul
title CROIT Uptime Monitoring

echo.
echo  ============================================
echo   CROIT Uptime Monitoring - Starting...
echo  ============================================
echo.

cd /d "%~dp0"

IF NOT EXIST "venv\Scripts\activate.bat" (
    echo  [1/3] Creating Python virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo  ERROR: Python not found. Please install Python 3.x
        pause
        exit /b 1
    )
    echo  Done.
    echo.
)

echo  [2/3] Activating environment and checking dependencies...
call venv\Scripts\activate.bat
pip install -q -r requirements.txt --quiet
echo  Done.
echo.

echo  [3/3] Starting server...
echo.
echo  ============================================
echo   Open browser at:  http://localhost:5000
echo.
echo   Status pages:
echo     http://localhost:5000/?page=default
echo     http://localhost:5000/?page=fnbcroit-status
echo.
echo   Press Ctrl+C to stop the server
echo  ============================================
echo.

set PYTHONIOENCODING=utf-8
python app.py
