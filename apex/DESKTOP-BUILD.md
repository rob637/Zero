# Telic Desktop App

One-click installable Windows desktop app, built with Tauri + PyInstaller.

## How It Works

```
┌──────────────────────────────────────────┐
│      Tauri (Rust) — Native Window        │
│  ┌────────────────────────────────────┐  │
│  │  WebView → ui/index.html           │  │
│  └────────────────────────────────────┘  │
│        │ HTTP (localhost:8000)            │
│        ▼                                 │
│  ┌────────────────────────────────────┐  │
│  │  apex-server.exe (PyInstaller)      │  │
│  │  FastAPI + Connectors + Agent       │  │
│  │  (bundled as Tauri sidecar)         │  │
│  └────────────────────────────────────┘  │
│                                          │
│  System Tray: Show/Hide/Quit             │
│  Close button → hides to tray            │
└──────────────────────────────────────────┘
```

The user gets a single `.exe` installer. No Python installation needed.

## Quick Build (Windows)

```
build-desktop.bat
```

This runs all steps automatically. The installer lands in:
`apex/src-tauri/target/release/bundle/nsis/Telic_0.1.0_x64-setup.exe`

## Manual Build Steps

### Prerequisites

- **Python 3.11+** — [python.org](https://www.python.org/downloads/)
- **Node.js 18+** — [nodejs.org](https://nodejs.org/)
- **Rust** — [rustup.rs](https://rustup.rs/)

### 1. Build Python backend

```bash
cd apex
pip install -r requirements.txt
pip install pyinstaller
pyinstaller apex-server.spec --noconfirm --clean
```

This creates `dist/apex-server/` — the entire Python app as a standalone directory.

### 2. Prepare sidecar

```bash
# Get your Rust target triple
rustc -vV | grep host

# Copy to Tauri's expected location (example for x86_64-pc-windows-msvc)
mkdir -p src-tauri/binaries
xcopy /E /I dist\apex-server src-tauri\binaries\apex-server-x86_64-pc-windows-msvc
copy dist\apex-server\apex-server.exe src-tauri\binaries\apex-server-x86_64-pc-windows-msvc.exe
```

### 3. Build Tauri app

```bash
npm install
npm run build
```

### Output

| File | Location |
|------|----------|
| NSIS installer | `src-tauri/target/release/bundle/nsis/Telic_*_x64-setup.exe` |
| MSI installer | `src-tauri/target/release/bundle/msi/Telic_*.msi` |

## CI/CD

Push a git tag (`v0.1.0`) to trigger automated builds via GitHub Actions.
The workflow installs all toolchains, builds the backend, bundles the sidecar,
and uploads the installer as a build artifact.

## Development

```bash
# Terminal 1: Start Python server
cd apex
python server.py

# Terminal 2: Start Tauri dev (live-reloads the window)
cd apex
npm run dev
```

## Icons

To regenerate icons from a source PNG:
```bash
npx @tauri-apps/cli icon path/to/icon-1024x1024.png
```
