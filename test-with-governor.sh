#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# test-with-governor.sh — Start a governor daemon, run Maude tests against it, tear down.
#
# Usage:
#   bash test-with-governor.sh              # Claude Code backend (default)
#   bash test-with-governor.sh --codex      # Codex backend
#   bash test-with-governor.sh --ollama     # Ollama backend (needs ollama running)
#   bash test-with-governor.sh --mock       # Degraded mode (no real backend)
#
# Prerequisites:
#   - agent_gov installed (governor CLI available)
#
# Environment overrides:
#   AGENT_GOV_DIR   — path to agent_gov repo (default: ../agent_gov)
#   PYTEST_ARGS     — extra args for pytest (default: -v --tb=short)

set -euo pipefail

# --- Configuration -----------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_GOV_DIR="${AGENT_GOV_DIR:-$SCRIPT_DIR/../agent_gov}"
PYTEST_ARGS="${PYTEST_ARGS:--v --tb=short}"
REAL_HOME=$(eval echo "~$(whoami)")
BACKEND_TYPE="claude-code"
GOVERNOR_PID=""
GOV_DIR=""
SOCKET_PATH=""

# --- Argument parsing ---------------------------------------------------------

for arg in "$@"; do
    case "$arg" in
        --codex)    BACKEND_TYPE="codex" ;;
        --ollama)   BACKEND_TYPE="ollama" ;;
        --mock)     BACKEND_TYPE="ollama" ;;  # points nowhere → degraded
        --help|-h)
            echo "Usage: bash test-with-governor.sh [--codex|--ollama|--mock]"
            echo ""
            echo "Starts a governor daemon, runs Maude's tests against it, tears down."
            echo ""
            echo "Options:"
            echo "  --codex    Use Codex backend (needs codex installed)"
            echo "  --ollama   Use Ollama backend (needs ollama running)"
            echo "  --mock     Degraded mode — no real backend (good for contract tests)"
            echo "  (default)  Claude Code backend (needs claude installed)"
            echo ""
            echo "Environment:"
            echo "  AGENT_GOV_DIR   Path to agent_gov repo (default: ../agent_gov)"
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
        echo "--- Stopping governor daemon (PID $GOVERNOR_PID) ---"
        kill "$GOVERNOR_PID" 2>/dev/null || true
        wait "$GOVERNOR_PID" 2>/dev/null || true
    fi
    # Clean up socket file
    if [ -n "$SOCKET_PATH" ] && [ -S "$SOCKET_PATH" ]; then
        rm -f "$SOCKET_PATH"
    fi
    # Clean up temp governor dir
    if [ -n "$GOV_DIR" ] && [ -d "$GOV_DIR" ]; then
        rm -rf "$GOV_DIR"
    fi
}
trap cleanup EXIT INT TERM

# --- Verify agent_gov ---------------------------------------------------------

if ! command -v governor &>/dev/null; then
    if [ -d "$AGENT_GOV_DIR" ]; then
        echo "Installing agent_gov in dev mode..."
        PIP_FLAGS=""
        if ! pip3 install --dry-run --quiet pip 2>/dev/null; then
            PIP_FLAGS="--user --break-system-packages"
        fi
        pip3 install -e "$AGENT_GOV_DIR" $PIP_FLAGS --quiet
    else
        echo "ERROR: governor CLI not found and agent_gov repo not at $AGENT_GOV_DIR"
        exit 1
    fi
fi

# Ensure maude itself is importable
if ! python3 -c "import maude" 2>/dev/null; then
    echo "Installing maude in dev mode..."
    PIP_FLAGS=""
    if ! pip3 install --dry-run --quiet pip 2>/dev/null; then
        PIP_FLAGS="--user --break-system-packages"
    fi
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
    if command -v codex &>/dev/null; then
        command -v codex
        return
    fi
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

# --- Initialize temp governor directory ---------------------------------------

GOV_DIR=$(mktemp -d /tmp/maude-test-gov.XXXXXX)
governor --root "$GOV_DIR" init
echo "Governor dir: $GOV_DIR"

# --- Start daemon -------------------------------------------------------------

SOCKET_PATH="${XDG_RUNTIME_DIR:-/tmp}/maude-test-$$.sock"
echo "Starting governor daemon (socket: $SOCKET_PATH)..."

governor --root "$GOV_DIR" serve --socket "$SOCKET_PATH" --mode code &
GOVERNOR_PID=$!

# --- Wait for socket ----------------------------------------------------------

echo -n "Waiting for daemon socket"
MAX_WAIT=30
for i in $(seq 1 $MAX_WAIT); do
    if [ -S "$SOCKET_PATH" ]; then
        echo " OK (${i}s)"
        break
    fi
    if ! kill -0 "$GOVERNOR_PID" 2>/dev/null; then
        echo " FAILED"
        echo "ERROR: Daemon process exited prematurely."
        exit 1
    fi
    echo -n "."
    sleep 1
done

# Final check
if [ ! -S "$SOCKET_PATH" ]; then
    echo " TIMEOUT"
    echo "ERROR: Daemon socket did not appear within ${MAX_WAIT}s."
    exit 1
fi

echo "Daemon is running (PID $GOVERNOR_PID)."
echo ""

# --- Run tests ----------------------------------------------------------------

echo "--- Running Maude tests ---"
echo "GOVERNOR_SOCKET=$SOCKET_PATH"
echo "GOVERNOR_DIR=$GOV_DIR"
echo ""

GOVERNOR_SOCKET="$SOCKET_PATH" \
GOVERNOR_DIR="$GOV_DIR" \
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
