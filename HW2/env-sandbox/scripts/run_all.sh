#!/bin/bash
# HW2 任务一：两组各跑 3 轮（run-1/2/3）
cd /workspace/HW2/src/target1 || exit 1
for r in run-1 run-2 run-3; do
  echo "=== shared_prefix $r ==="
  python3 run_benchmark.py --group shared_prefix --run-id "$r" \
    > /workspace/HW2/results/target1/shared_prefix/$r.log 2>&1
  echo "=== dispersed_prefix $r ==="
  python3 run_benchmark.py --group dispersed_prefix --run-id "$r" \
    > /workspace/HW2/results/target1/dispersed_prefix/$r.log 2>&1
done
echo ALL_RUNS_DONE
