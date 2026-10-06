#!/usr/bin/env bash
set -uo pipefail
export PIP_NO_CACHE_DIR=1
cd /root/HW3-姓名/src/target3
echo "=== setup_env start: Mon Oct  5 11:08:31 CST 2026 ==="
bash setup_env.sh 2>&1
echo "setup_env exit: $?"
echo "=== download_model start: Mon Oct  5 11:08:31 CST 2026 ==="
bash download_model.sh 2>&1
echo "download_model exit: $?"
echo "=== conda clean ==="
/root/miniconda3/bin/conda clean -afy -q 2>&1 | tail -2
echo "=== BOOTSTRAP DONE: Mon Oct  5 11:08:31 CST 2026 ==="
df -h / | tail -1
