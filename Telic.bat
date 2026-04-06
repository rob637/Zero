@echo off
title Telic - Starting...
color 0B

echo.
echo  =============================
echo       TELIC
echo    The AI Operating System
echo  =============================
echo.

:: Get the directory where this script is located
cd /d "%~dp0"

:: Load .env file if it exists (API keys live here)
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        set "%%a=%%b"
    )
)

:: Check for Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.11+
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Check for API key
if "%ANTHROPIC_API_KEY%"=="" (
    if "%OPENAI_API_KEY%"=="" (
        echo [WARNING] No API key found.
        echo.
        echo Create a .env file in this folder with:
        echo   ANTHROPIC_API_KEY=your-key-here
        echo.
        echo Get a key from: https://console.anthropic.com
        echo.
    )
)

:: Auto-setup if first run (venv lives in apex/)
cd apex
if not exist ".venv" (
    echo First run detected - running setup...
    echo.
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt --quiet
    echo.
) else (
    call .venv\Scripts\activate.bat
)

echo Starting Telic...
echo.

:: Start the browser after a short delay
start "" cmd /c "timeout /t 2 >nul && start http://localhost:8000"

:: Run the server
python server.py

:: If we get here, server stopped
echo.
echo Telic stopped.
pause
