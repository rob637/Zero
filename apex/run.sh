#!/usr/bin/env bash
# Telic - Quick Launch
# Usage: ./run.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Auto-setup if first run
if [ ! -d ".venv" ]; then
    echo "First run detected — running setup..."
    echo ""
    bash setup.sh
    exit $?
fi

source .venv/bin/activate

# Check for API key
if [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠  No API key set. Run ./setup.sh or:"
    echo "   export ANTHROPIC_API_KEY=\"your-key-here\""
    echo ""
fi

echo "Starting Telic..."
(sleep 2 && python3 -m webbrowser "http://localhost:8000") &
python3 server.py
