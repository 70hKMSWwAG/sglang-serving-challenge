#!/usr/bin/env bash
#
# HW3 target3: stop everything (SGLang servers, serve_app.py, Ray).
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HW3_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$HW3_ROOT/logs"
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
RAY_PY="$CONDA_BASE/envs/ray-env/bin/python"
[ -x "$RAY_PY" ] || RAY_PY="python3"

echo "==> stopping serve_app.py"
pkill -f "serve_app.py" 2>/dev/null || true

echo "==> stopping SGLang servers"
for i in 0 1 2 3; do
  PIDFILE="$LOG_DIR/sglang-$i.pid"
  if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE")"
    if kill -0 "$PID" 2>/dev/null; then
      echo "    killing sglang-$i (pid $PID)"
      kill "$PID" 2>/dev/null || true
    fi
    rm -f "$PIDFILE"
  fi
done
# Belt and suspenders: anything still matching the launch command.
pkill -f "sglang.launch_server" 2>/dev/null || true

echo "==> ray stop"
"$RAY_PY" -m ray stop --force 2>/dev/null || ray stop --force 2>/dev/null || true

sleep 2
echo "==> remaining processes:"
pgrep -af "serve_app.py|sglang.launch_server" || echo "    none"
