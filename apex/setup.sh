#!/usr/bin/env bash
set -e

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo -e "${BLUE}"
echo "  _____ _____ _     ___ ____ "
echo " |_   _| ____| |   |_ _/ ___|"
echo "   | | |  _| | |    | | |    "
echo "   | | | |___| |___ | | |___ "
echo "   |_| |_____|_____|___\____|"
echo -e "${NC}"
echo " The AI Operating System with Purpose"
echo " ======================================"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Step 1: Check for Python ──
echo "[1/4] Checking for Python..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}  Python 3 not found!${NC}"
    echo ""
    echo "  Install Python 3.11+:"
    echo "    macOS:  brew install python3"
    echo "    Ubuntu: sudo apt install python3 python3-venv python3-pip"
    echo ""
    exit 1
fi
echo -e "  $(python3 --version) ${GREEN}✓${NC}"
echo ""

# ── Step 2: Create virtual environment ──
echo "[2/4] Creating virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "  Created .venv ${GREEN}✓${NC}"
else
    echo -e "  .venv already exists ${GREEN}✓${NC}"
fi
source .venv/bin/activate
echo ""

# ── Step 3: Install dependencies ──
echo "[3/4] Installing dependencies..."
pip install -e ".[dev]" --quiet 2>/dev/null || pip install -r requirements.txt --quiet
echo -e "  Dependencies installed ${GREEN}✓${NC}"
echo ""

# ── Step 4: API key check ──
echo "[4/4] Checking for API key..."
if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo -e "  Anthropic API key found ${GREEN}✓${NC}"
elif [ -n "$OPENAI_API_KEY" ]; then
    echo -e "  OpenAI API key found ${GREEN}✓${NC}"
else
    echo -e "${YELLOW}"
    echo "  ┌──────────────────────────────────────────────────┐"
    echo "  │  No API key found.                               │"
    echo "  │                                                  │"
    echo "  │  Telic needs an LLM API key to work.             │"
    echo "  │  Get one from:                                   │"
    echo "  │    https://console.anthropic.com  (recommended)  │"
    echo "  │    https://platform.openai.com                   │"
    echo "  └──────────────────────────────────────────────────┘"
    echo -e "${NC}"
    read -p "  Paste your Anthropic API key (or press Enter to skip): " API_KEY
    if [ -n "$API_KEY" ]; then
        export ANTHROPIC_API_KEY="$API_KEY"
        echo ""
        echo "  export ANTHROPIC_API_KEY=\"$API_KEY\"" >> ~/.bashrc 2>/dev/null || true
        echo "  export ANTHROPIC_API_KEY=\"$API_KEY\"" >> ~/.zshrc 2>/dev/null || true
        echo -e "  API key saved ${GREEN}✓${NC}"
        echo "  (Added to .bashrc/.zshrc for future sessions)"
    else
        echo "  Skipped — set it later with:"
        echo "    export ANTHROPIC_API_KEY=\"your-key-here\""
    fi
fi

echo ""
echo -e "${GREEN}"
echo "  ┌──────────────────────────────────────────────────┐"
echo "  │                                                  │"
echo "  │   Setup complete!                                │"
echo "  │                                                  │"
echo "  │   To launch Telic, run:                          │"
echo "  │     ./run.sh                                     │"
echo "  │                                                  │"
echo "  └──────────────────────────────────────────────────┘"
echo -e "${NC}"

read -p "Launch Telic now? (Y/n): " LAUNCH
if [ "$LAUNCH" = "n" ] || [ "$LAUNCH" = "N" ]; then
    echo "Goodbye!"
    exit 0
fi

echo "Starting Telic..."
(for i in $(seq 1 120); do
    if curl -fsS "http://localhost:8000/health" >/dev/null 2>&1; then
        python3 -m webbrowser "http://localhost:8000"
        exit 0
    fi
    sleep 0.5
done
python3 -m webbrowser "http://localhost:8000") &
python3 server.py
