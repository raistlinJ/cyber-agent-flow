#!/bin/bash
# script to safely initialize host dependencies and run the Kali WebUI in Docker

echo "[agentflow] Checking for required host tools..."

echo "[agentflow] Setting up python environment via uv..."

# 1. Ensure uv is installed
if ! command -v uv &> /dev/null; then
    if [ -x "$HOME/.local/bin/uv" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo "Installing uv locally..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi

UV_BIN=$(command -v uv || echo "$HOME/.local/bin/uv")

# 2. Pre-cache uv dependencies for offline support
if [[ "$*" == *"--build"* ]]; then
    echo "[agentflow] Pre-caching Python dependencies for offline support..."
    "$UV_BIN" run --with mcp --with requests --with flask --with ollama python3 -c "print('Dependencies cached.')" 2>/dev/null || true
fi

echo "[agentflow] Starting Docker Compose..."
if [[ "$*" == *"--build"* ]]; then
    echo "[agentflow] --build flag detected, rebuilding image..."
    docker-compose up -d --build
else
    docker-compose up -d
fi

# Start kali_server.py REST API in the background (required for APT package mode)
if [ -f /usr/share/mcp-kali-server/kali_server.py ]; then
    echo "[agentflow] Starting kali_server.py REST API on port 5000..."
    pkill -f 'kali_server.py' 2>/dev/null || true; sleep 1
    setsid "$UV_BIN" run --offline --with flask python3 /usr/share/mcp-kali-server/kali_server.py >/tmp/kali_server.log 2>&1 &
    # Wait up to 30s for it to be ready
    for i in $(seq 1 30); do
        nc -z localhost 5000 2>/dev/null && echo "[agentflow] kali_server.py ready on port 5000" && break
        sleep 1
    done
else
    echo "[agentflow] Skipping kali_server.py (not found — APT package mode unavailable)"
fi

echo "[agentflow] WebUI is running on http://localhost:5055"
