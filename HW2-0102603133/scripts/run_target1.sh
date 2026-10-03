#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${BASE:-http://127.0.0.1:30000}"

python3 "$ROOT/src/target1/measure_prefix_cache.py" \
  --base "$BASE" \
  --results-root "$ROOT/results/target1"

python3 "$ROOT/src/render_report.py"
