#!/bin/bash
# script to safely initialize environments and run the Kali WebUI locally

set -e

echo "[cyber-agentflow] Checking for required tools..."

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
PYTHON_BIN="$VENV_DIR/bin/python"
BUILD_MODE=0

if [[ "$*" == *"--build"* ]]; then
    BUILD_MODE=1
fi

echo "[cyber-agentflow] Using persistent virtual environment at $VENV_DIR"

# 1. Create venv on demand
if [ ! -x "$PYTHON_BIN" ]; then
    echo "[cyber-agentflow] Virtual environment not found; creating it..."
    if command -v python3 >/dev/null 2>&1; then
        python3 -m venv "$VENV_DIR"
    else
        echo "[cyber-agentflow] ERROR: python3 is required to create the virtual environment."
        exit 1
    fi
    BUILD_MODE=1
fi

# 2. Install dependencies only when explicitly building or after first-time venv creation
if [ "$BUILD_MODE" -eq 1 ]; then
    echo "[cyber-agentflow] Installing Python dependencies into the persistent venv..."
    "$PYTHON_BIN" -m pip install --upgrade pip
    "$PYTHON_BIN" -m pip install -r "$PROJECT_DIR/requirements.txt"
else
    echo "[cyber-agentflow] Verifying installed Python dependencies..."
    # ``pynput`` initialises its platform backend during a normal import and
    # therefore raises when CAF is launched headlessly over SSH (no X display),
    # even though the package is correctly installed.  Keylogging is optional
    # and app.py already disables it gracefully in that environment; verify
    # the package exists without initialising its desktop backend.
    if ! "$PYTHON_BIN" -c "import flask, requests, mcp, ollama, importlib.util; assert importlib.util.find_spec('pynput')" >/dev/null 2>&1; then
        echo "[cyber-agentflow] ERROR: Required Python dependencies are missing from $VENV_DIR"
        echo "[cyber-agentflow] Run ./start_ws.sh --build once while online to install them."
        exit 1
    fi
fi

# Start kali_server.py REST API in the background (required for APT package mode)
if [ -f /usr/share/mcp-kali-server/kali_server.py ]; then
    echo "[cyber-agentflow] Starting kali_server.py REST API on port 5000..."
    pkill -f 'kali_server.py' 2>/dev/null || true; sleep 1
    setsid "$PYTHON_BIN" /usr/share/mcp-kali-server/kali_server.py >/tmp/kali_server.log 2>&1 &
    # Wait up to 30s for it to be ready
    for i in $(seq 1 30); do
        nc -z localhost 5000 2>/dev/null && echo "[cyber-agentflow] kali_server.py ready on port 5000" && break
        sleep 1
    done
else
    echo "[cyber-agentflow] Skipping kali_server.py (not found — APT package mode unavailable)"
fi

# Use the persistent venv to run the flask application without re-resolving dependencies
echo "[cyber-agentflow] Starting Flask server..."
exec "$PYTHON_BIN" "$PROJECT_DIR/app.py"
