@echo off
title Telic - First Time Setup
color 0B

echo.
echo  =============================
echo       TELIC - Setup
echo    The AI Operating System
echo  =============================
echo.

:: Get the directory where this script is located
cd /d "%~dp0"

:: ── Step 1: Check for Python ──
echo [1/4] Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ╔══════════════════════════════════════════════════╗
    echo  ║  Python not found!                               ║
    echo  ║                                                  ║
    echo  ║  Download Python 3.11+ from:                     ║
    echo  ║  https://www.python.org/downloads/               ║
    echo  ║                                                  ║
    echo  ║  IMPORTANT: Check "Add Python to PATH"           ║
    echo  ║  during installation!                            ║
    echo  ╚══════════════════════════════════════════════════╝
    echo.
    start https://www.python.org/downloads/
    echo After installing Python, run this setup again.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo   Found %%v ✓
echo.

:: ── Step 2: Create virtual environment ──
echo [2/4] Creating virtual environment...
if not exist ".venv" (
    python -m venv .venv
    echo   Created .venv ✓
) else (
    echo   .venv already exists ✓
)
echo.

:: ── Step 3: Install dependencies ──
echo [3/4] Installing dependencies (this may take a minute)...
call .venv\Scripts\activate.bat
pip install -e ".[dev]" --quiet 2>nul
if %errorlevel% neq 0 (
    echo   Trying fallback install...
    pip install -r requirements.txt --quiet
)
echo   Dependencies installed ✓
echo.

:: ── Step 4: API key check ──
echo [4/4] Checking for API key...
if not "%ANTHROPIC_API_KEY%"=="" (
    echo   Anthropic API key found ✓
    goto :setup_done
)
if not "%OPENAI_API_KEY%"=="" (
    echo   OpenAI API key found ✓
    goto :setup_done
)

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║  No API key found.                               ║
echo  ║                                                  ║
echo  ║  Telic needs an LLM API key to work.             ║
echo  ║  You can get one from:                           ║
echo  ║    - https://console.anthropic.com  (recommended)║
echo  ║    - https://platform.openai.com                 ║
echo  ╚══════════════════════════════════════════════════╝
echo.
set /p "API_KEY=Paste your Anthropic API key (or press Enter to skip): "
if not "%API_KEY%"=="" (
    setx ANTHROPIC_API_KEY "%API_KEY%" >nul 2>&1
    set "ANTHROPIC_API_KEY=%API_KEY%"
    echo   API key saved to your environment ✓
    echo   (You may need to restart your terminal for it to take effect)
) else (
    echo   Skipped — you can set it later with:
    echo     setx ANTHROPIC_API_KEY "your-key-here"
)

:setup_done
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║                                                  ║
echo  ║   Setup complete!                                ║
echo  ║                                                  ║
echo  ║   To launch Telic, double-click:                 ║
echo  ║     Telic.bat       (console mode)               ║
echo  ║     Telic.ps1       (system tray mode)           ║
echo  ║                                                  ║
echo  ╚══════════════════════════════════════════════════╝
echo.
set /p "LAUNCH=Launch Telic now? (Y/n): "
if /i "%LAUNCH%"=="n" (
    echo Goodbye!
    pause
    exit /b 0
)

echo Starting Telic...
start "" cmd /c "timeout /t 2 >nul && start http://localhost:8000"
python server.py
pause
