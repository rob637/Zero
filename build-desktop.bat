@echo off
title Telic - Desktop Build
color 0B

echo.
echo  =============================
echo    TELIC - Desktop App Build
echo  =============================
echo.

cd /d "%~dp0"

:: ── Prerequisites check ──
echo [1/5] Checking prerequisites...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found. Install from https://www.python.org/downloads/
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version') do echo   Python: %%v [OK]

node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Node.js not found. Install from https://nodejs.org/
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do echo   Node.js: %%v [OK]

cargo --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Rust not found. Install from https://rustup.rs/
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('cargo --version') do echo   %v [OK]
echo.

:: ── Step 2: Python virtual environment ──
echo [2/5] Setting up Python environment...
cd apex
if not exist ".venv" (
    python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet
echo   Python environment ready [OK]
echo.

:: ── Step 3: Build Python backend with PyInstaller ──
echo [3/5] Building Python backend (this takes a few minutes)...
pyinstaller apex-server.spec --noconfirm --clean
if %errorlevel% neq 0 (
    echo  ERROR: PyInstaller build failed
    pause & exit /b 1
)
echo   Backend built [OK]
echo.

:: ── Step 4: Copy sidecar to Tauri binaries ──
echo [4/5] Preparing Tauri sidecar...

:: Determine target triple
for /f "tokens=*" %%t in ('rustc -vV ^| findstr "host:"') do set "RUST_TARGET=%%t"
set "RUST_TARGET=%RUST_TARGET:host: =%"
echo   Target: %RUST_TARGET%

set "SIDECAR_DIR=src-tauri\binaries"
if not exist "%SIDECAR_DIR%" mkdir "%SIDECAR_DIR%"

:: Copy the PyInstaller output directory
:: Tauri sidecar expects: binaries/apex-server-{target}
set "SIDECAR_NAME=apex-server-%RUST_TARGET%"
if exist "%SIDECAR_DIR%\%SIDECAR_NAME%" rmdir /s /q "%SIDECAR_DIR%\%SIDECAR_NAME%"
xcopy /E /I /Q "dist\apex-server" "%SIDECAR_DIR%\%SIDECAR_NAME%"

:: Tauri also needs the .exe at the expected path
copy /Y "dist\apex-server\apex-server.exe" "%SIDECAR_DIR%\%SIDECAR_NAME%.exe" >nul
echo   Sidecar prepared [OK]
echo.

:: ── Step 5: Build Tauri app ──
echo [5/5] Building Tauri desktop app...
cd ..
npm install --silent 2>nul
cd apex
npm run build
if %errorlevel% neq 0 (
    echo  ERROR: Tauri build failed
    pause & exit /b 1
)
echo.

echo  =============================
echo   Build complete!
echo  =============================
echo.
echo  Installer location:
echo    apex\src-tauri\target\release\bundle\nsis\
echo.
echo  Look for: Telic_0.1.0_x64-setup.exe
echo.
pause
