#!/usr/bin/env bash
# Orchestrate all five rounds of HW3 target 3, in order:
#   A (p2c, 5), B1 (p2c, 16), B2 (p2c, 32), C (consistent hash), D (improved)
# Each round: redeploy the Serve app, flush all four SGLang caches, replay.
# B_MAX_ONGOING is the admission value chosen from B1/B2; defaults to 32.
set -euo pipefail

COURSE_DIR="${COURSE_DIR:?set COURSE_DIR to the course workload directory}"
RESULTS_ROOT="${RESULTS_ROOT:-results/target3}"
WORKLOAD_FILE="$COURSE_DIR/mooncake_prefix_workload_v2_seed2026.jsonl"
RAY_PY="${RAY_PY:-/root/autodl-tmp/envs/rayenv/bin/python}"
B_MAX_ONGOING="${B_MAX_ONGOING:-32}"

"$RAY_PY" "$COURSE_DIR/validate_workload.py" "$WORKLOAD_FILE"
./launch_backends.sh

./run_group.sh A  A_default      "$RESULTS_ROOT/A_default"
./run_group.sh B1 B1_candidate_1 "$RESULTS_ROOT/B_candidates/candidate-1"
./run_group.sh B2 B2_candidate_2 "$RESULTS_ROOT/B_candidates/candidate-2"
./run_group.sh C  C_affinity     "$RESULTS_ROOT/C_affinity"
B_MAX_ONGOING=$B_MAX_ONGOING ./run_group.sh D  D_improved "$RESULTS_ROOT/D_improved"

echo "all rounds finished"
