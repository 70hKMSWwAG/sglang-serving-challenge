#!/usr/bin/env bash
# run_target1.sh —— 任务一：一键完成「启动服务 → 两组前缀缓存测量」
#
# 用法（在 WSL 内，SGLang 环境的 python 由 env.sh 提供）：
#     sudo bash run_target1.sh                 # 默认 run-1，顺序 shared → dispersed
#     sudo bash run_target1.sh run-2 dispersed,shared
#
# 参数：
#     $1  运行标签（结果落在 results/target1/<标签>/），默认 run-1
#     $2  两组执行顺序，shared,dispersed 或 dispersed,shared，默认 shared,dispersed
#
# 前置条件：环境已由 01_setup_env.sh 构建（编译过 sgl-kernel），
#           并已生成 /mnt/d/first-task/work/env.sh。
#           若尚未构建：sudo bash ../env/01_setup_env.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HW2="$(cd "$HERE/../.." && pwd)"          # .../HW2-林彦超
ENVD="$HERE/../env"
WORK="${WORK:-/mnt/d/first-task}"

TAG="${1:-run-1}"
ORDER="${2:-shared,dispersed}"

if [ ! -f "$WORK/work/env.sh" ]; then
  echo "缺少 $WORK/work/env.sh —— 请先执行: sudo bash $ENVD/01_setup_env.sh" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$WORK/work/env.sh"
# shellcheck disable=SC1090
source "$ENVD/00_common.sh"

SRV_LOG="${LOGD}/sglang_server.log"

log "==================== 任务一：前缀缓存测量（$TAG） ===================="

# ---------- 1) 确保 SGLang 服务在线 ----------
if curl -s --noproxy '*' --max-time 5 "${BASE}/v1/models" 2>/dev/null | grep -q '"id"'; then
  ok "SGLang 服务已在线：${BASE}"
else
  log "服务未就绪，调用 02_start_server.sh 启动"
  bash "$ENVD/02_start_server.sh" || die "服务启动失败"
fi

# 记录本次实验对应的软件版本与服务端关键配置，供报告溯源
# （运行级信息，写入两个组目录各一份，与交付目录 results/target1/<组>/<tag>/ 对齐）
VINFO="$(mktemp)"
{
  echo "### 运行时间"; date --iso-8601=seconds
  echo "### SGLang 版本"; "$VENV/bin/python" -c "import sglang;print(sglang.__version__)" 2>&1
  echo "### Ray 版本"; "$RAYVENV/bin/python" -c "import ray;print(ray.__version__)" 2>&1
  echo "### torch"; "$VENV/bin/python" -c "import torch;print(torch.__version__)" 2>&1
  echo "### CPU"; grep -m1 'model name' /proc/cpuinfo
  echo "### nproc"; nproc
  echo "### 服务端 KV/缓存配置（取自服务端日志）"
  grep -E "KV Cache is allocated|max_total_num_tokens|Tree cache initialized|max_running_requests|page_size" \
      "$SRV_LOG" 2>/dev/null | tail -12
} > "$VINFO" 2>&1
for gdir in shared_prefix dispersed_prefix; do
  mkdir -p "$HW2/results/target1/$gdir/$TAG"
  cp "$VINFO" "$HW2/results/target1/$gdir/$TAG/version_info.log"
done
rm -f "$VINFO"
ok "版本信息已记录到 results/target1/{shared_prefix,dispersed_prefix}/${TAG}/version_info.log"

# ---------- 2) 执行两组测量 ----------
"$VENV/bin/python" "$HERE/prefix_cache_bench.py" \
    --host "$HOST" --port "$PORT" \
    --model-dir "$MODEL_DIR" \
    --out-root "$HW2/results/target1" \
    --server-log "$SRV_LOG" \
    --n 32 --concurrency 8 \
    --prefix-tokens 2048 --suffix-tokens 64 \
    --tag "$TAG" --order "$ORDER"
rc=$?

if [ "$rc" -eq 0 ]; then
  ok "任务一测量完成：$HW2/results/target1/$TAG"
else
  die "任务一测量失败（退出码 $rc），请检查上方输出"
fi
