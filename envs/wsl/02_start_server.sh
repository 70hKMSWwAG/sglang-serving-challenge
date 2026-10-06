#!/usr/bin/env bash
# 02_start_server.sh —— 启动 Ray head + SGLang OpenAI-compatible 服务
#   bash /mnt/d/first-task/wsl/02_start_server.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${WORK:-/mnt/d/first-task}/work/env.sh" ] && [ ! -f /mnt/d/first-task/work/env.sh ]; then
  echo "找不到 work/env.sh，请先执行 01_setup_env.sh"; exit 1
fi
source /mnt/d/first-task/work/env.sh
# env.sh 只导出变量，不含函数；这里补 source 公共库以拿到 log/ok/warn/wait_ready
source "${WSLD:-/mnt/d/first-task/wsl}/00_common.sh"

log "==================== 阶段 2/5：启动服务 ===================="

# ---------- 2.1 先启动 Ray 2.56.0 head（独立 Python 环境，与 SGLang 通过 HTTP 通信） ----------
if "${RAYVENV}/bin/python" -c "import ray" 2>/dev/null; then
  if "${RAYVENV}/bin/ray" status >/dev/null 2>&1; then
    ok "Ray 已在运行"
  else
    log "启动 Ray head（${RAY_VER}）"
    "${RAYVENV}/bin/ray" start --head --port=6379 --dashboard-host=127.0.0.1 \
      --disable-usage-stats >"${LOGD}/ray_start.log" 2>&1 \
      && ok "Ray head 已启动" || warn "Ray 启动失败（不阻塞 SGLang）"
  fi
  { echo "### ray version"; "${RAYVENV}/bin/python" -c "import ray;print(ray.__version__)";
    echo "### ray status"; "${RAYVENV}/bin/ray" status 2>&1 | head -25; } \
    | tee "${LOGD}/01_ray_status.log" >/dev/null
  ok "Ray 状态已记录"
else
  warn "Ray 环境不可用，跳过"
fi

# ---------- 2.2 启动 SGLang（OpenAI-compatible，CPU 引擎） ----------
if curl -s --noproxy '*' --max-time 3 "${BASE}/v1/models" 2>/dev/null | grep -q '"id"'; then
  ok "SGLang 服务已在 ${BASE} 运行"
else
  log "启动 SGLang 服务: ${MODEL_DIR}"
  log "  SGLANG_USE_CPU_ENGINE=${SGLANG_USE_CPU_ENGINE:-1}  LD_PRELOAD=${LD_PRELOAD:-<空>}"
  cd "${SRC}"
  export SGLANG_USE_CPU_ENGINE=1
  nohup "${VENV}/bin/python" -m sglang.launch_server \
      --model-path "${MODEL_DIR}" \
      --device cpu \
      --host "${HOST}" \
      --port "${PORT}" \
      --tp 1 \
      --trust-remote-code \
      --disable-overlap-schedule \
      --mem-fraction-static "${MEM_FRACTION:-0.80}" \
      >"${LOGD}/sglang_server.log" 2>&1 &
  echo $! > "${OUTD}/sglang.pid"
  ok "已拉起进程 PID=$(cat "${OUTD}/sglang.pid")，日志 ${LOGD}/sglang_server.log"
fi

if wait_ready "${READY_TIMEOUT:-1800}"; then
  echo "=== SERVER READY ==="
else
  echo "=== 启动失败，服务日志尾部 ==="
  tail -40 "${LOGD}/sglang_server.log" 2>/dev/null
  exit 1
fi
