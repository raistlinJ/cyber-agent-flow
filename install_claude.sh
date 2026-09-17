#!/usr/bin/env bash
# Install/verify the native Claude Code CLI used for artifact generation.
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"
mode="${1:-install}"
if [[ "$mode" != "install" && "$mode" != "--check" && "$mode" != "--update" ]]; then
    echo "Usage: $0 [--check|--update]" >&2
    exit 2
fi

verify_claude() {
    local binary="${CYBER_AGENT_FLOW_CLAUDE_BIN:-}"
    if [[ -z "$binary" ]]; then binary="$(command -v claude || true)"; fi
    [[ -n "$binary" && -x "$binary" ]] || return 1
    local help
    help="$("$binary" --help)" || return 1
    for required in --bare --tools --settings --setting-sources --permission-mode --no-session-persistence; do
        if [[ "$help" != *"$required"* ]]; then
            echo "[claude] Installed CLI lacks $required; update Claude Code." >&2
            return 1
        fi
    done
    "$binary" --version
}

if [[ "$mode" != "--update" ]] && verify_claude; then
    echo "[claude] Claude Code is ready for artifact generation."
    exit 0
fi
if [[ "$mode" == "--check" ]]; then
    echo "[claude] Run ./install_claude.sh to install a compatible Claude Code CLI." >&2
    exit 1
fi
if [[ -n "${CYBER_AGENT_FLOW_CLAUDE_BIN:-}" ]]; then
    echo "[claude] CYBER_AGENT_FLOW_CLAUDE_BIN is invalid or incompatible; fix it before installing." >&2
    exit 1
fi
command -v curl >/dev/null || { echo "[claude] curl is required." >&2; exit 1; }
installer="$(mktemp)"
trap 'rm -f "$installer"' EXIT
curl --fail --silent --show-error --location https://claude.ai/install.sh --output "$installer"
bash "$installer" "${CYBER_AGENT_FLOW_CLAUDE_VERSION:-stable}"
verify_claude || { echo "[claude] Native installation could not be verified." >&2; exit 1; }
echo "[claude] Native installation verified. No cloud login is needed for your configured local inference endpoint."
