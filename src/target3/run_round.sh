#!/usr/bin/env bash
#
# HW3 target3: run one full experimental round for a group.
#
# Usage:
#   run_round.sh <GROUP> [RUN_INDEX]
#
# GROUP: A_default | B_cand1 | B_cand2 | C_affinity | D_improved
#
# Each round, in the order required by the course README:
#   1. stop any previous Ray Serve app and redeploy with this round's config
#   2. POST /flush_cache on all 4 SGLang backends (must all succeed)
#   3. replay with the COURSE's official traffic generator (run_workload.py):
#      64 warmup requests (sequential), then 2048 measured requests
#   4. check the exit status + summary.json, then tear the Serve app down
#
# Results land in results/target3/<group-dir>/run-<RUN_INDEX>/ with the
# official artifacts: config.json, warmups.csv, requests.csv, summary.json.
#
# Group -> config mapping (router-name / max-ongoing-requests are recorded
# into config.json by run_workload.py and MUST match the Serve deployment):
#
#   A_default  -> p2c,            max_ongoing=5            results/target3/A_default
#   B_cand1    -> p2c,            max_ongoing=16           results/target3/B_candidates/candidate-1
#   B_cand2    -> p2c,            max_ongoing=64           results/target3/B_candidates/candidate-2
#   C_affinity -> consistent_hash,max_ongoing=$B_PICK      results/target3/C_affinity
#   D_improved -> affinity_load_aware, max_ongoing=$B_PICK results/target3/D_improved
#
# Env knobs:
#   B_PICK        chosen max_ongoing_requests for C/D (default 32; set it to
#               the winner of the B candidates before running C/D)
#   WORKLOAD_DIR  course workload dir (default: <repo>/_workload_repo/
#               workloads/hw2/target3-routing-policies)
#   RAY_PYTHON    python of ray-env (auto-detected)
#   BASE_PORT     SGLang base port (default 30000)
#   SERVE_PORT    Ray Serve HTTP port (default 8000)
#   OVERWRITE=1   allow rerunning into an existing output dir
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HW3_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$HW3_ROOT/logs"
mkdir -p "$LOG_DIR"

# NOTE (2026-10-05): the official traffic generator opens one TCP connection
# per in-flight request (TCPConnector(limit=0), --max-in-flight 2048). With the
# container default soft limit of 1024 fds, every request past ~1100 failed with
# OSError(24, 'Too many open files') -- 873/2048 failures in the first A run.
# Raise the soft limit to the hard limit so all 2048 requests can be served.
ULIMIT_NOFILE="$(ulimit -Hn)"
if [ "$ULIMIT_NOFILE" = "unlimited" ] || [ -z "$ULIMIT_NOFILE" ]; then
  ULIMIT_NOFILE=65535
fi
ulimit -n "$ULIMIT_NOFILE" 2>/dev/null || echo "WARNING: cannot raise ulimit -n (current: $(ulimit -n))"
echo "==> ulimit -n = $(ulimit -n)"

GROUP="${1:?usage: run_round.sh <A_default|B_cand1|B_cand2|C_affinity|D_improved> [RUN_INDEX]}"
RUN_INDEX="${2:-1}"
B_PICK="${B_PICK:-64}"
BASE_PORT="${BASE_PORT:-30000}"
SERVE_PORT="${SERVE_PORT:-8000}"
# Course workload dir: prefer <repo>/workloads/..., fall back to the cloned
# 26fall-HW-data layout <repo>/_workload_repo/workloads/hw2/...
if [ -z "${WORKLOAD_DIR:-}" ]; then
  if [ -f "$HW3_ROOT/workloads/target3-routing-policies/run_workload.py" ]; then
    WORKLOAD_DIR="$HW3_ROOT/workloads/target3-routing-policies"
  else
    WORKLOAD_DIR="$HW3_ROOT/_workload_repo/workloads/hw2/target3-routing-policies"
  fi
fi

case "$GROUP" in
  A_default)
    ROUTER_MODE=A_default; ROUTER_NAME=p2c; MAX_ONGOING=5
    OUT="$HW3_ROOT/results/target3/A_default/run-$RUN_INDEX" ;;
  B_cand1)
    ROUTER_MODE=B_cand1; ROUTER_NAME=p2c; MAX_ONGOING=16
    OUT="$HW3_ROOT/results/target3/B_candidates/candidate-1/run-$RUN_INDEX" ;;
  B_cand2)
    ROUTER_MODE=B_cand2; ROUTER_NAME=p2c; MAX_ONGOING=64
    OUT="$HW3_ROOT/results/target3/B_candidates/candidate-2/run-$RUN_INDEX" ;;
  C_affinity)
    ROUTER_MODE=C_affinity; ROUTER_NAME=consistent_hash; MAX_ONGOING="$B_PICK"
    OUT="$HW3_ROOT/results/target3/C_affinity/run-$RUN_INDEX" ;;
  D_improved)
    ROUTER_MODE=D_improved; ROUTER_NAME=affinity_load_aware; MAX_ONGOING="$B_PICK"
    OUT="$HW3_ROOT/results/target3/D_improved/run-$RUN_INDEX" ;;
  *)
    echo "ERROR: unknown GROUP '$GROUP'" >&2; exit 1 ;;
esac

# -- python of ray-env -------------------------------------------------------
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
if [ -n "${RAY_PYTHON:-}" ]; then
  :
elif [ -x "$CONDA_BASE/envs/ray-env/bin/python" ]; then
  RAY_PYTHON="$CONDA_BASE/envs/ray-env/bin/python"
else
  RAY_PYTHON="python3"
fi
echo "==> group=$GROUP run=$RUN_INDEX mode=$ROUTER_MODE router=$ROUTER_NAME max_ongoing=$MAX_ONGOING"
echo "==> python: $RAY_PYTHON"
echo "==> output: $OUT"

if [ ! -f "$WORKLOAD_DIR/run_workload.py" ]; then
  echo "ERROR: workload dir not found: $WORKLOAD_DIR" >&2
  echo "Clone it next to this repo or set WORKLOAD_DIR." >&2
  exit 1
fi
WORKLOAD_JSON="$WORKLOAD_DIR/mooncake_prefix_workload_v2_seed2026.jsonl"

# -- 0. preflight: SGLang backends up -----------------------------------------
for i in 0 1 2 3; do
  PORT=$((BASE_PORT + i))
  if ! curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
    echo "ERROR: SGLang backend $i (port $PORT) not ready; run launch_sglang.sh first." >&2
    exit 1
  fi
done
echo "==> 4 SGLang backends reachable"

# -- 1. (re)deploy the Serve app with this round's config ----------------------
echo "==> stopping any previous Serve app"
pkill -f "serve_app.py" 2>/dev/null || true
"$RAY_PYTHON" -m ray stop --force >/dev/null 2>&1 || true
sleep 3

SERVE_LOG="$LOG_DIR/serve-$GROUP-run$RUN_INDEX.log"
export HW3_ROUTER_LOG="$OUT/router_fallbacks.jsonl"   # group D fallback journal
mkdir -p "$OUT"
echo "==> deploying Serve app (log: $SERVE_LOG)"
cd "$SCRIPT_DIR"
# NOTE (2026-10-05): Ray 2.56.0 Serve needs the pure-Python protobuf
# implementation (FieldDescriptor.label was removed from the upb backend).
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python
nohup "$RAY_PYTHON" serve_app.py \
  --router-mode "$ROUTER_MODE" \
  --max-ongoing-requests "$MAX_ONGOING" \
  --serve-port "$SERVE_PORT" \
  --sglang-base-port "$BASE_PORT" \
  >"$SERVE_LOG" 2>&1 &
echo $! >"$LOG_DIR/serve_app.pid"

echo "==> waiting for Serve /healthz"
READY=0
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$SERVE_PORT/healthz" >/dev/null 2>&1; then
    READY=1; break
  fi
  sleep 5
done
if [ "$READY" != "1" ]; then
  echo "ERROR: Serve did not become ready; see $SERVE_LOG" >&2
  tail -50 "$SERVE_LOG" >&2 || true
  exit 1
fi
echo "==> Serve ready:"
curl -s "http://127.0.0.1:$SERVE_PORT/healthz"; echo

# -- 2. flush all 4 SGLang caches ----------------------------------------------
echo "==> flushing SGLang caches"
for i in 0 1 2 3; do
  PORT=$((BASE_PORT + i))
  CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/flush_cache")"
  if [ "$CODE" != "200" ]; then
    echo "ERROR: /flush_cache on backend $i returned HTTP $CODE" >&2
    exit 1
  fi
  echo "    backend $i cache flushed"
done

# -- 3. replay with the official traffic generator ------------------------------
echo "==> validating workload file"
"$RAY_PYTHON" "$WORKLOAD_DIR/validate_workload.py" "$WORKLOAD_JSON"

RUN_NAME="${GROUP}_run${RUN_INDEX}"
# Client-side per-request timeout of the official generator (default 300s).
# Group A (max_ongoing=5) drains its queue in ~330s, so the last requests hit
# the 300s budget; re-run group A with TIMEOUT_S=900 to let it complete.
TIMEOUT_S="${TIMEOUT_S:-300}"
ARGS=( --policy serve --run-name "$RUN_NAME"
  --router-name "$ROUTER_NAME" --max-ongoing-requests "$MAX_ONGOING"
  --base-url "http://127.0.0.1:$SERVE_PORT"
  --workload "$WORKLOAD_JSON" --max-in-flight 2048
  --timeout "$TIMEOUT_S"
  --output-dir "$OUT"
  --metadata "group=$GROUP" --metadata "router_mode=$ROUTER_MODE" )
if [ "${OVERWRITE:-0}" = "1" ]; then ARGS+=( --overwrite ); fi

echo "==> replaying workload -> $OUT"
set +e
"$RAY_PYTHON" "$WORKLOAD_DIR/run_workload.py" "${ARGS[@]}" >"$OUT/replay_stdout.log" 2>&1
RC=$?
set -e
tail -5 "$OUT/replay_stdout.log"

# -- 4. teardown ------------------------------------------------------------------
echo "==> tearing down Serve app"
pkill -f "serve_app.py" 2>/dev/null || true
"$RAY_PYTHON" -m ray stop --force >/dev/null 2>&1 || true
sleep 2

if [ "$RC" != "0" ]; then
  echo "ERROR: run_workload.py exited with status $RC (round INVALID); see $OUT" >&2
  exit "$RC"
fi
echo "==> round VALID: $OUT/summary.json"
"$RAY_PYTHON" -c "
import json
s = json.load(open('$OUT/summary.json'))
print('successful:', s['successful'], '/', s['requests'], '| failed:', s['failed'], '| incomplete:', s['incomplete'])
print('throughput_rps: %.2f' % s['throughput_rps'], '| cache_hit_rate: %.4f' % s['cache_hit_rate'])
print('backend_distribution:', s['backend_distribution'])
print('validation_errors:', s['validation_errors'])
"
