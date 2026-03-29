# Apex Desktop App

Native Windows desktop application built with Tauri.

## Development Setup

### Prerequisites

1. **Rust** - Install from [rustup.rs](https://rustup.rs/)
2. **Node.js** - Install from [nodejs.org](https://nodejs.org/)
3. **Python 3.11+** - For the backend server

### Install Dependencies

```bash
# Install Tauri CLI
npm install

# Install Python dependencies
pip install -r requirements.txt
```

### Run in Development

```bash
# Option 1: Run everything together
npm run dev

# Option 2: Run separately (useful for debugging)
# Terminal 1: Start Python server
python server.py

# Terminal 2: Start Tauri dev
npm run tauri dev
```

### Build for Production

```bash
npm run build
```

This creates an installer in `src-tauri/target/release/bundle/`.

## Architecture

```
┌─────────────────────────────────────────┐
│           Tauri (Rust)                  │
│  ┌─────────────────────────────────┐    │
│  │    Native Window + System Tray   │    │
│  └─────────────────────────────────┘    │
│              │                          │
│              ▼                          │
│  ┌─────────────────────────────────┐    │
│  │      WebView (Chromium)         │    │
│  │   ┌─────────────────────────┐   │    │
│  │   │   Our UI (HTML/CSS/JS)   │   │    │
│  │   └─────────────────────────┘   │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
              │ HTTP
              ▼
┌─────────────────────────────────────────┐
│        Python Backend (FastAPI)         │
│  ┌────────┐ ┌────────┐ ┌────────────┐  │
│  │ Skills │ │ Memory │ │ LLM Client │  │
│  └────────┘ └────────┘ └────────────┘  │
└─────────────────────────────────────────┘
```

## Icons

Generate icons using [tauri-icon](https://tauri.app/v1/guides/features/icons):

```bash
npm install -g @tauri-apps/cli
tauri icon path/to/your/icon.png
```

Place a 1024x1024 PNG and it generates all sizes.

## Production Build (with bundled Python)

For a fully standalone .exe that doesn't require Python:

1. Build Python server with PyInstaller:
   ```bash
   pip install pyinstaller
   pyinstaller --onefile --name apex-server server.py
   ```

2. Configure Tauri to use it as sidecar in `tauri.conf.json`

3. Build the full app:
   ```bash
   npm run build
   ```
