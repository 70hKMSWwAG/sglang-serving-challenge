#!/usr/bin/env bash
# Run one experiment group: (re)deploy the Serve app, flush all backends,
# then replay the fixed workload through the Ray Serve HTTP entry.
#
# Usage: ./run_group.sh <GROUP> <RUN_NAME> <RESULTS_DIR> [EXTRA run_workload args]
# GROUP config table (must match deploy_app.py):
#   A   p2c 5 | B1 p2c 16 | B2 p2c 32 | C consistent_hash <B> | D affinity_load <B>
set -euo pipefail

GROUP="$1"; RUN_NAME="$2"; RESULTS_DIR="$3"; shift 3

COURSE_DIR="${COURSE_DIR:?set COURSE_DIR to the course workload directory (26fall-HW-data/workloads/hw2/target3-routing-policies)}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
WORKLOAD="${WORKLOAD:-$COURSE_DIR/mooncake_prefix_workload_v2_seed2026.jsonl}"
RAY_PY="${RAY_PY:-/root/autodl-tmp/envs/rayenv/bin/python}"
RAY_BIN="$(dirname "$RAY_PY")"
export PATH="$RAY_BIN:$PATH"

case "$GROUP" in
  A)  ROUTER=p2c;              MQR=5;;
  B1) ROUTER=p2c;              MQR=16;;
  B2) ROUTER=p2c;              MQR=32;;
  C)  ROUTER=consistent_hash;  MQR="${B_MAX_ONGOING:-32}";;
  D)  ROUTER=affinity_load;    MQR="${B_MAX_ONGOING:-32}";;
  *)  echo "unknown group $GROUP"; exit 1;;
esac

# 0. Stop a previous deploy_app.py and tear the Ray cluster down, so each round
#    starts from a freshly built 1 head + 4 worker topology.
pkill -f "deploy_app.py" 2>/dev/null || true
"$RAY_BIN/ray" stop --force >/dev/null 2>&1 || true
sleep 5

# 1. Redeploy the app with this round's configuration.
GROUP=$GROUP ROUTER_NAME=$ROUTER MAX_ONGOING=$MQR "$RAY_PY" deploy_app.py --group "$GROUP" \
  --router-name "$ROUTER" --max-ongoing-requests "$MQR" &
DEPLOY_PID=$!
# wait for the READY line
for _ in $(seq 1 120); do
  if ! kill -0 $DEPLOY_PID 2>/dev/null; then
    echo "deploy_app.py exited early; see its output"; exit 1
  fi
  if curl -s "$BASE_URL/generate" -o /dev/null 2>/dev/null; then break; fi
  sleep 2
done
echo "Serve app deployed (pid $DEPLOY_PID)"

# 2. Flush all four SGLang caches.
"$RAY_PY" flush_backends.py

# 3. Replay the fixed workload.
"$RAY_PY" "$COURSE_DIR/run_workload.py" \
  --policy serve \
  --run-name "$RUN_NAME" \
  --router-name "$ROUTER" \
  --max-ongoing-requests "$MQR" \
  --base-url "$BASE_URL" \
  --workload "$WORKLOAD" \
  --max-in-flight 2048 \
  --output-dir "$RESULTS_DIR" \
  "$@"

echo "group $GROUP done: $RESULTS_DIR"
