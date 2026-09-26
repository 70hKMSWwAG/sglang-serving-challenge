#!/usr/bin/env bash
# run_all.sh —— 全流程一键执行（构建 → 起服务 → 单次推理 → Mooncake 压测）
#
# 用法（WSL 内）：
#   sudo bash /mnt/d/first-task/wsl/run_all.sh
# 或分步执行：
#   01_setup_env.sh  →  02_start_server.sh  →  03_single_request.sh  →  04_benchmark.py
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTD=/mnt/d/first-task/work
LOGD="${OUTD}/logs"
mkdir -p "$LOGD"
MAIN="${LOGD}/run_all.log"

step() {
  local name="$1"; shift
  echo "" | tee -a "$MAIN"
  echo "############################################################" | tee -a "$MAIN"
  echo "# >>> $name    $(date '+%F %T')" | tee -a "$MAIN"
  echo "############################################################" | tee -a "$MAIN"
  { "$@" ; } 2>&1 | tee -a "$MAIN"
  local rc=${PIPESTATUS[0]}
  echo "# <<< $name 退出码=$rc" | tee -a "$MAIN"
  return $rc
}

step "1/4 环境搭建"      bash "$HERE/01_setup_env.sh"
step "2/4 启动服务"      bash "$HERE/02_start_server.sh"
step "3/4 单次推理(截图1)" bash "$HERE/03_single_request.sh"

echo "---- 4/4 Mooncake trace 采样压测(截图2) ----" | tee -a "$MAIN"
source "${OUTD}/env.sh"
step "4/4 Poisson 压测" \
  "${VENV}/bin/python" "$HERE/04_benchmark.py" --n "${N:-20}" --mean-interval "${MI:-6.0}" | tee -a "$MAIN"

echo "" | tee -a "$MAIN"
echo "==================== 全流程结束 $(date '+%F %T') ====================" | tee -a "$MAIN"
echo "产物目录: ${OUTD}"
ls -la "${OUTD}/results" | tee -a "$MAIN"
