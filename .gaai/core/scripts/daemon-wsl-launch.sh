#!/usr/bin/env bash
# WSL daemon launcher — sources login profile so claude is in PATH, then starts daemon with nohup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

LOCK_DIR="$PROJECT_ROOT/.gaai/project/contexts/backlog/.delivery-locks"
LOG_FILE="$PROJECT_ROOT/.gaai/project/contexts/backlog/.delivery-daemon.log"
PID_FILE="$LOCK_DIR/.daemon.pid"
GAAI_WORKTREE_BASE="$PROJECT_ROOT/.gaai/worktrees"

mkdir -p "$LOCK_DIR" "$(dirname "$LOG_FILE")" "$GAAI_WORKTREE_BASE"

# Source login profile, then prepend ~/.local/bin (holds the claude symlink)
# .bashrc on this machine overrides PATH with the Windows PATH (omitting ~/.local/bin),
# so we re-add it afterwards.
[[ -f "$HOME/.bashrc" ]] && source "$HOME/.bashrc" 2>/dev/null || true
[[ -f "$HOME/.bash_profile" ]] && source "$HOME/.bash_profile" 2>/dev/null || true
export PATH="$HOME/.local/bin:$PATH"

# Verify claude is available
if ! command -v claude &>/dev/null; then
  echo "ERROR: claude CLI not found even after sourcing profile" >&2
  exit 1
fi
echo "claude found: $(which claude)"

# Kill any existing daemon
if [[ -f "$PID_FILE" ]]; then
  OLD_PID=$(cat "$PID_FILE")
  kill -0 "$OLD_PID" 2>/dev/null && kill "$OLD_PID" 2>/dev/null || true
  rm -f "$PID_FILE"
fi

# Launch daemon with nohup, preserving PATH
nohup env PATH="$PATH" GAAI_WORKTREE_BASE="$GAAI_WORKTREE_BASE" bash "$SCRIPT_DIR/delivery-daemon.sh" "$@" >> "$LOG_FILE" 2>&1 &
DAEMON_PID=$!
echo "$DAEMON_PID" > "$PID_FILE"
echo "Daemon started with PID $DAEMON_PID (log: $LOG_FILE)"
sleep 3
kill -0 "$DAEMON_PID" 2>/dev/null && echo "Process alive — OK" || echo "Process exited early — check log"
tail -5 "$LOG_FILE"
