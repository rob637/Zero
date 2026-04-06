@echo off
title Telic - Starting...
color 0B

echo.
echo  _____ _____ _     ___ ____
echo ^|_   _^| ____^| ^|   ^|_ _^/ ___|
echo   ^| ^| ^|  _^| ^| ^|    ^| ^| ^|
echo   ^| ^| ^| ^|___^| ^|___ ^| ^| ^|___
echo   ^|_^| ^|_____^|_____^|___\____^|
echo.
echo The AI Operating System with Purpose
echo =====================================
echo.

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
        echo Set one of these environment variables:
        echo   $env:ANTHROPIC_API_KEY = "your-key"
        echo   $env:OPENAI_API_KEY = "your-key"
        echo.
        echo Or set it permanently in System Environment Variables.
        echo.
    )
)

:: Get the directory where this script is located
cd /d "%~dp0"

:: Auto-setup if first run
if not exist ".venv" (
    echo First run detected — running setup...
    echo.
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -e ".[dev]" --quiet 2>nul || pip install -r requirements.txt --quiet
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
