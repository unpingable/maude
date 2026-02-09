#!/usr/bin/env bash
# test-with-governor.sh — Start a live governor, run Maude tests against it, tear down.
#
# Usage:
#   bash test-with-governor.sh              # Claude Code backend (default)
#   bash test-with-governor.sh --codex      # Codex backend
#   bash test-with-governor.sh --ollama     # Ollama backend (needs ollama running)
#   bash test-with-governor.sh --mock       # Degraded mode (no real backend)
#
# Prerequisites:
#   - gov-webui repo at GOV_WEBUI_DIR (default: ../gov-webui)
#   - pip install -e "../gov-webui"  (script will check)
#
# Environment overrides:
#   GOV_WEBUI_DIR   — path to gov-webui repo (default: ../gov-webui)
#   GOVERNOR_PORT   — port for governor (default: 8321, avoids 8000 conflicts)
#   PYTEST_ARGS     — extra args for pytest (default: -v --tb=short)

set -euo pipefail

# --- Configuration -----------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GOV_WEBUI_DIR="${GOV_WEBUI_DIR:-$SCRIPT_DIR/../gov-webui}"
GOVERNOR_PORT="${GOVERNOR_PORT:-8321}"
GOVERNOR_URL="http://127.0.0.1:${GOVERNOR_PORT}"
PYTEST_ARGS="${PYTEST_ARGS:--v --tb=short}"
REAL_HOME=$(eval echo "~$(whoami)")
BACKEND_TYPE="claude-code"
GOVERNOR_PID=""

# --- Argument parsing ---------------------------------------------------------

for arg in "$@"; do
    case "$arg" in
        --codex)    BACKEND_TYPE="codex" ;;
        --ollama)   BACKEND_TYPE="ollama" ;;
        --mock)     BACKEND_TYPE="ollama" ;;  # points nowhere → degraded
        --help|-h)
            echo "Usage: bash test-with-governor.sh [--codex|--ollama|--mock]"
            echo ""
            echo "Starts a governor, runs Maude's tests against it, tears down."
            echo ""
            echo "Options:"
            echo "  --codex    Use Codex backend (needs codex installed)"
            echo "  --ollama   Use Ollama backend (needs ollama running)"
            echo "  --mock     Degraded mode — no real backend (good for contract tests)"
            echo "  (default)  Claude Code backend (needs claude installed)"
            echo ""
            echo "Environment:"
            echo "  GOV_WEBUI_DIR   Path to gov-webui repo (default: ../gov-webui)"
            echo "  GOVERNOR_PORT   Port for governor (default: 8321)"
            echo "  PYTEST_ARGS     Extra pytest args (default: -v --tb=short)"
            exit 0
            ;;
        *)
            echo "Unknown argument: $arg"
            echo "Run with --help for usage."
            exit 1
            ;;
    esac
done

# --- Cleanup trap -------------------------------------------------------------

cleanup() {
    if [ -n "$GOVERNOR_PID" ] && kill -0 "$GOVERNOR_PID" 2>/dev/null; then
        echo ""
        echo "--- Stopping governor (PID $GOVERNOR_PID) ---"
        kill "$GOVERNOR_PID" 2>/dev/null || true
        wait "$GOVERNOR_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# --- Verify agent_gov ---------------------------------------------------------

GOV_WEBUI_DIR="${GOV_WEBUI_DIR:-$SCRIPT_DIR/../gov-webui}"

if [ ! -d "$GOV_WEBUI_DIR/src/gov_webui" ]; then
    echo "ERROR: gov-webui not found at $GOV_WEBUI_DIR"
    echo "Set GOV_WEBUI_DIR to the path of the gov-webui repo."
    exit 1
fi

# Check webui extras are installed
PIP_FLAGS=""
# Detect if we need --user --break-system-packages (externally managed envs)
if ! pip3 install --dry-run --quiet pip 2>/dev/null; then
    PIP_FLAGS="--user --break-system-packages"
fi

if ! python3 -c "import uvicorn; import starlette" 2>/dev/null; then
    echo "Installing gov-webui dependencies..."
    pip3 install -e "${GOV_WEBUI_DIR}" $PIP_FLAGS --quiet
fi

# Ensure maude itself is importable
if ! python3 -c "import maude" 2>/dev/null; then
    echo "Installing maude in dev mode..."
    pip3 install -e "$SCRIPT_DIR" $PIP_FLAGS --quiet
fi

# --- Detect backend binary ----------------------------------------------------

detect_claude() {
    local versions_dir="$REAL_HOME/.local/share/claude/versions"
    if [ ! -d "$versions_dir" ]; then
        echo "ERROR: Claude Code not found at $versions_dir"
        echo "Install Claude Code or use --codex / --ollama / --mock"
        exit 1
    fi
    local version
    version=$(ls "$versions_dir" | sort -V | tail -1)
    local binary="$versions_dir/$version"
    if [ ! -x "$binary" ]; then
        echo "ERROR: Claude binary not executable: $binary"
        exit 1
    fi
    echo "$binary"
}

detect_codex() {
    # Try PATH first
    if command -v codex &>/dev/null; then
        command -v codex
        return
    fi
    # Try nvm location
    local node_version
    node_version=$(node --version 2>/dev/null | sed 's/^v//' || true)
    if [ -z "$node_version" ]; then
        echo "ERROR: Node.js not found (needed for Codex)"
        exit 1
    fi
    local arch
    arch=$(uname -m)
    case "$arch" in
        x86_64)  arch="x86_64-unknown-linux-musl" ;;
        aarch64) arch="aarch64-unknown-linux-musl" ;;
        arm64)   arch="aarch64-unknown-linux-musl" ;;
        *)       echo "ERROR: Unsupported arch: $arch"; exit 1 ;;
    esac
    local binary="$REAL_HOME/.nvm/versions/node/v${node_version}/lib/node_modules/@openai/codex/vendor/${arch}/codex/codex"
    if [ ! -x "$binary" ]; then
        echo "ERROR: Codex binary not found at $binary"
        exit 1
    fi
    echo "$binary"
}

export GOVERNOR_MODE="code"
export GOVERNOR_CONTEXT_ID="maude-test"

case "$BACKEND_TYPE" in
    claude-code)
        CLAUDE_PATH=$(detect_claude)
        export BACKEND_TYPE
        export CLAUDE_PATH
        echo "Backend: Claude Code ($CLAUDE_PATH)"
        ;;
    codex)
        CODEX_PATH=$(detect_codex)
        export BACKEND_TYPE
        export CODEX_PATH
        echo "Backend: Codex ($CODEX_PATH)"
        ;;
    ollama)
        export BACKEND_TYPE
        if [ "${1:-}" = "--mock" ]; then
            export OLLAMA_URL="http://127.0.0.1:99999"  # unreachable → degraded
            echo "Backend: Mock (degraded mode, no real LLM)"
        else
            export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
            echo "Backend: Ollama ($OLLAMA_URL)"
        fi
        ;;
esac

# --- Start governor -----------------------------------------------------------

echo "Starting governor on port $GOVERNOR_PORT..."

python3 -m uvicorn gov_webui.adapter:app \
    --host 127.0.0.1 \
    --port "$GOVERNOR_PORT" \
    --log-level warning \
    &
GOVERNOR_PID=$!

# --- Wait for health ----------------------------------------------------------

echo -n "Waiting for governor health"
MAX_WAIT=30
for i in $(seq 1 $MAX_WAIT); do
    if curl -sf "${GOVERNOR_URL}/health" >/dev/null 2>&1; then
        echo " OK (${i}s)"
        break
    fi
    if ! kill -0 "$GOVERNOR_PID" 2>/dev/null; then
        echo " FAILED"
        echo "ERROR: Governor process exited prematurely."
        exit 1
    fi
    echo -n "."
    sleep 1
done

# Final check
if ! curl -sf "${GOVERNOR_URL}/health" >/dev/null 2>&1; then
    echo " TIMEOUT"
    echo "ERROR: Governor did not become healthy within ${MAX_WAIT}s."
    exit 1
fi

# Print health status
echo "Governor health:"
curl -sf "${GOVERNOR_URL}/health" | python3 -m json.tool 2>/dev/null || true
echo ""

# --- Run tests ----------------------------------------------------------------

echo "--- Running Maude tests ---"
echo "GOVERNOR_URL=$GOVERNOR_URL"
echo ""

GOVERNOR_URL="$GOVERNOR_URL" \
    python3 -m pytest "$SCRIPT_DIR/tests/" $PYTEST_ARGS
TEST_EXIT=$?

# --- Report -------------------------------------------------------------------

echo ""
if [ $TEST_EXIT -eq 0 ]; then
    echo "All tests passed."
else
    echo "Tests failed (exit code: $TEST_EXIT)."
fi

exit $TEST_EXIT
