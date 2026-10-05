#!/usr/bin/env bash
# Run all 5 target3 rounds sequentially (A, B1, B2, C, D) with the fd fix.
# B_PICK is fixed to 64 (expected winner of the two B candidates: it had both
# higher throughput and lower latency in the pre-fix runs); if the post-fix B
# numbers contradict this, C/D are simply re-run with the other value.
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"

export OVERWRITE=1
export B_PICK=64
# Uniform client-side timeout for ALL groups (default 300s truncated group A
# and C, whose queues drain in ~330s; B/D never come close, so this only
# removes artificial failures, it does not change their numbers).
export TIMEOUT_S=900

for g in A_default B_cand1 B_cand2 C_affinity D_improved; do
  echo "############################################################"
  echo "### ROUND $g  $(date -u +%FT%TZ)"
  echo "############################################################"
  bash run_round.sh "$g" 1
  echo "### exit=$? for $g"
  sleep 5
done
echo "ALL ROUNDS DONE $(date -u +%FT%TZ)"
