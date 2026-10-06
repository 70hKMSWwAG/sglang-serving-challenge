#!/usr/bin/env bash
#
# HW3 target3: launch 4 SGLang servers (ports 30000-30003), one per backend.
#
#   NUM_GPUS=4 (default): server i gets CUDA_VISIBLE_DEVICES=i and
#             --mem-fraction-static 0.85  (a whole GPU each)
#   NUM_GPUS=1          : all 4 servers share GPU 0, each with
#             --mem-fraction-static 0.22  (~5.3 GB of a 24 GB card per server:
#             ~1.3 GB weights + ~4 GB KV pool; enough for the workload because
#             shared prefixes dedupe in the radix cache)
#
# Do NOT disable the radix cache here -- prefix reuse is exactly what the
# experiment measures. SGLang enables it by default.
#
# The script waits until /v1/models answers on all 4 ports, then exits,
# leaving the servers running (logs in logs/, pids in logs/).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HW3_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$HW3_ROOT/logs"
mkdir -p "$LOG_DIR"

MODEL_PATH="${MODEL_PATH:-$HOME/workspace/hw3/models/Qwen3-0.6B}"
NUM_GPUS="${NUM_GPUS:-4}"
BASE_PORT="${BASE_PORT:-30000}"
MEM_FRAC_4GPU="${MEM_FRAC_4GPU:-0.85}"
# NOTE (2026-10-05): on a single 24 GB card, 4 servers must share. SGLang
# 0.5.14 needs >= 0.238 per server just for weights with CUDA graphs on,
# which would leave ~zero KV cache and make prefix-reuse unmeasurable.
# We disable CUDA graphs (--disable-cuda-graph) to free that memory for the
# KV/radix cache. Empirically (2026-10-05), 4 concurrent servers OOM at
# 0.24 (weights are loaded 4x); 0.18 works with staggered startup.
MEM_FRAC_1GPU="${MEM_FRAC_1GPU:-0.18}"
# NOTE (2026-10-05): see above -- CUDA graphs eat GBs of per-server memory
# (prefill graphs are captured up to batch 2048 by default). The routing
# comparison does not need them; the KV cache matters far more here.
DISABLE_CUDA_GRAPH="${DISABLE_CUDA_GRAPH:-1}"
# NOTE (2026-10-05): the container's CUDA toolkit is 11.8, but the
# flashinfer JIT needs CUDA >= 12 to compile its kernels, so the default
# flashinfer attention backend crashes on first prefill. We use the triton
# backend instead (self-contained JIT, no system nvcc needed). The radix
# cache / prefix-reuse logic is backend-independent, so the routing
# comparison stays valid. Documented in README as well.
ATTN_BACKEND="${ATTN_BACKEND:-triton}"
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
SGLANG_PY="$CONDA_BASE/envs/sglang-env/bin/python"

# flashinfer JIT-compiles CUDA kernels on first prefill and needs `ninja`
# (pip-installed into sglang-env) plus nvcc on PATH. The servers below are
# launched with the env python directly (no `conda activate`), so we export
# the PATH explicitly.
#
# NOTE (2026-10-05): the container toolkit (/usr/local/cuda) is CUDA 11.8,
# but SGLang 0.5.14's JIT kernels need `-std=c++20`, which requires nvcc from
# CUDA >= 12. We pip-installed `nvidia-cuda-nvcc-cu12` and built a compat
# toolchain at ~/cuda13_compat (nvcc 13 binaries + CUDA 11.8 headers/lib64,
# which tvm-ffi/flashinfer resolve via CUDA_HOME).
if [ -x "$HOME/cuda13_compat/bin/nvcc" ]; then
  export CUDA_HOME="$HOME/cuda13_compat"
else
  export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
fi
NVCC12_BIN="$(ls -d "$CONDA_BASE"/envs/sglang-env/lib/python3.*/site-packages/nvidia/cu*/bin 2>/dev/null | head -1)"
export PATH="$CONDA_BASE/envs/sglang-env/bin:${NVCC12_BIN:+$NVCC12_BIN:}${CUDA_HOME:+$CUDA_HOME/bin:}/usr/local/cuda/bin:$PATH"

if [ ! -x "$SGLANG_PY" ]; then
  echo "ERROR: $SGLANG_PY not found; run setup_env.sh first." >&2
  exit 1
fi
if [ ! -d "$MODEL_PATH" ]; then
  echo "ERROR: model dir $MODEL_PATH not found; run download_model.sh first." >&2
  exit 1
fi
if [ "$NUM_GPUS" != "1" ] && [ "$NUM_GPUS" != "4" ]; then
  echo "ERROR: NUM_GPUS must be 1 or 4 (got $NUM_GPUS)." >&2
  exit 1
fi

echo "==> launching 4 SGLang servers (model: $MODEL_PATH, NUM_GPUS=$NUM_GPUS)"
for i in 0 1 2 3; do
  PORT=$((BASE_PORT + i))
  if [ "$NUM_GPUS" = "4" ]; then
    CUDA_DEV="$i"
    MEM_FRAC="$MEM_FRAC_4GPU"
  else
    CUDA_DEV="0"
    MEM_FRAC="$MEM_FRAC_1GPU"
  fi
  LOG="$LOG_DIR/sglang-$i.log"
  PIDFILE="$LOG_DIR/sglang-$i.pid"
  echo "    backend $i -> 127.0.0.1:$PORT (CUDA_VISIBLE_DEVICES=$CUDA_DEV, mem-fraction-static=$MEM_FRAC)"
  CUDA_GRAPH_FLAG=""
  if [ "$DISABLE_CUDA_GRAPH" = "1" ]; then
    CUDA_GRAPH_FLAG="--disable-cuda-graph"
  fi
  CUDA_VISIBLE_DEVICES="$CUDA_DEV" nohup "$SGLANG_PY" -m sglang.launch_server \
    --model-path "$MODEL_PATH" \
    --host 127.0.0.1 --port "$PORT" \
    --mem-fraction-static "$MEM_FRAC" \
    --attention-backend "$ATTN_BACKEND" \
    $CUDA_GRAPH_FLAG \
    >"$LOG" 2>&1 &
  echo $! >"$PIDFILE"
done

echo "==> waiting for /v1/models on all 4 backends"
for i in 0 1 2 3; do
  PORT=$((BASE_PORT + i))
  for _ in $(seq 1 120); do
    if curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
      echo "    backend $i ready"
      break
    fi
    sleep 10
  done
  if ! curl -sf "http://127.0.0.1:$PORT/v1/models" >/dev/null 2>&1; then
    echo "ERROR: backend $i (port $PORT) did not become ready; see $LOG_DIR/sglang-$i.log" >&2
    exit 1
  fi
done
echo "==> all 4 SGLang backends ready"
