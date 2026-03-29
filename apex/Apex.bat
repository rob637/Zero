@echo off
title Apex - Starting...
color 0B

echo.
echo     ___    ____  _______  __
echo    /   \  ^|  _ \^| ____^\ \/ /
echo   / /_\ \ ^| ^|_) ^|  _^|  \  / 
echo  / _____ \^|  __/^| ^|___ /  \ 
echo /_/     \_\_^|   ^|_____/_/\_\
echo.
echo Privacy-First Personal AI Assistant
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

echo Starting Apex server...
echo.

:: Start the browser after a short delay
start "" cmd /c "timeout /t 2 >nul && start http://localhost:8000"

:: Run the server
python server.py

:: If we get here, server stopped
echo.
echo Apex server stopped.
pause
