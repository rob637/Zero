@echo off
title Telic - First Time Setup
color 0B
chcp 65001 >nul 2>&1

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
    echo  ERROR: Python not found!
    echo.
    echo  Download Python 3.11+ from:
    echo    https://www.python.org/downloads/
    echo.
    echo  IMPORTANT: Check "Add Python to PATH" during installation!
    echo.
    start https://www.python.org/downloads/
    echo After installing Python, run this setup again.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo   Found %%v [OK]
echo.

:: ── Step 2: Create virtual environment ──
echo [2/4] Creating virtual environment...
cd apex
if not exist ".venv" (
    python -m venv .venv
    echo   Created .venv [OK]
) else (
    echo   .venv already exists [OK]
)
echo.

:: ── Step 3: Install dependencies ──
echo [3/4] Installing dependencies (this may take a minute)...
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
echo   Dependencies installed [OK]
echo.
cd ..

:: ── Step 4: API key ──
echo [4/4] Setting up API key...

:: Check if .env already has a key
if exist ".env" (
    findstr /C:"ANTHROPIC_API_KEY" .env >nul 2>&1
    if not errorlevel 1 (
        echo   API key found in .env [OK]
        goto :setup_done
    )
)

:: Check environment variable
if not "%ANTHROPIC_API_KEY%"=="" (
    echo   Anthropic API key found in environment [OK]
    goto :setup_done
)
if not "%OPENAI_API_KEY%"=="" (
    echo   OpenAI API key found in environment [OK]
    goto :setup_done
)

echo.
echo  -----------------------------------------------
echo   No API key found.
echo.
echo   Telic needs an LLM API key to work.
echo   You can get one from:
echo     - https://console.anthropic.com  (recommended)
echo     - https://platform.openai.com
echo  -----------------------------------------------
echo.
set /p "API_KEY=Paste your Anthropic API key (or press Enter to skip): "
if not "%API_KEY%"=="" (
    echo ANTHROPIC_API_KEY=%API_KEY%> .env
    echo   API key saved to .env [OK]
) else (
    echo   Skipped. Create a .env file later with:
    echo     ANTHROPIC_API_KEY=your-key-here
)

:setup_done
echo.
echo  -----------------------------------------------
echo.
echo   Setup complete!
echo.
echo   To launch Telic, double-click: Telic.bat
echo.
echo  -----------------------------------------------
echo.
set /p "LAUNCH=Launch Telic now? (Y/n): "
if /i "%LAUNCH%"=="n" (
    echo Goodbye!
    pause
    exit /b 0
)

echo Starting Telic...
call Telic.bat
