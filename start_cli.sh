#!/bin/bash
# Initialize the local environment and run the CyberAgentFlow CLI.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
PYTHON_BIN="$VENV_DIR/bin/python"
BUILD_MODE=0

if [[ "$*" == *"--build"* ]]; then
    BUILD_MODE=1
fi

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

if [ "$BUILD_MODE" -eq 1 ]; then
    echo "[cyber-agentflow] Installing Python dependencies into the persistent venv..."
    "$PYTHON_BIN" -m pip install --upgrade pip
    "$PYTHON_BIN" -m pip install -r "$PROJECT_DIR/requirements.txt"
else
    if ! "$PYTHON_BIN" -c "import requests, mcp, ollama" >/dev/null 2>&1; then
        echo "[cyber-agentflow] ERROR: Required Python dependencies are missing from $VENV_DIR"
        echo "[cyber-agentflow] Run ./start_cli.sh --build once while online to install them."
        exit 1
    fi
fi

FILTERED_ARGS=()
for arg in "$@"; do
    if [ "$arg" != "--build" ]; then
        FILTERED_ARGS+=("$arg")
    fi
done

exec "$PYTHON_BIN" "$PROJECT_DIR/cli.py" "${FILTERED_ARGS[@]}"