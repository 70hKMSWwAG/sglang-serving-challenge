#!/usr/bin/env bash
#
# HW3 target3: download Qwen/Qwen3-0.6B weights.
#
# Tries ModelScope first (fast inside mainland China), then falls back to
# huggingface-cli with HF_MIRROR. Result goes to $MODEL_DIR
# (default: ~/workspace/hw3/models/Qwen3-0.6B).
#
# NOTE (2026-10-05): newer modelscope releases removed the `python -m modelscope`
# entry point, so the primary path uses the Python API
# (modelscope.snapshot_download). The huggingface fallback pins
# huggingface-hub<2 to avoid dependency conflicts with transformers/tokenizers
# shipped with sglang[all].
#
set -euo pipefail

MODEL_ID="${MODEL_ID:-Qwen/Qwen3-0.6B}"
MODEL_DIR="${MODEL_DIR:-$HOME/workspace/hw3/models/Qwen3-0.6B}"
CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

mkdir -p "$MODEL_DIR"

# Use sglang-env's python if present (it has modelscope as a dependency),
# otherwise plain python3.
if [ -x "$CONDA_BASE/envs/sglang-env/bin/python" ]; then
  PY="$CONDA_BASE/envs/sglang-env/bin/python"
else
  PY="python3"
fi

echo "==> target dir: $MODEL_DIR (using $PY)"

if ! "$PY" -c "import modelscope" 2>/dev/null; then
  echo "==> installing modelscope"
  "$PY" -m pip install modelscope -i "$PIP_INDEX" -q
fi

echo "==> downloading $MODEL_ID via ModelScope Python API"
if "$PY" -c "from modelscope import snapshot_download; snapshot_download('$MODEL_ID', local_dir='$MODEL_DIR')"; then
  echo "==> ModelScope download OK"
  ls -lh "$MODEL_DIR" | head -20
  exit 0
fi

echo "==> ModelScope API failed, trying modelscope console script"
if "$PY" -m pip show modelscope >/dev/null 2>&1 && "$CONDA_BASE/envs/sglang-env/bin/modelscope" download --model "$MODEL_ID" --local_dir "$MODEL_DIR"; then
  echo "==> modelscope CLI download OK"
  ls -lh "$MODEL_DIR" | head -20
  exit 0
fi

echo "==> falling back to huggingface-cli (HF_MIRROR, hub pinned <2)"
"$PY" -m pip install -q --no-deps "huggingface-hub>=1.5,<2.0" -i "$PIP_INDEX"
"$PY" -m pip install -q "huggingface_hub[cli]<2.0" -i "$PIP_INDEX"
export HF_MIRROR="${HF_MIRROR:-https://hf-mirror.com}"
"$PY" -m huggingface_hub.cli.huggingface_cli download "$MODEL_ID" --local-dir "$MODEL_DIR" --local-dir-use-symlinks False

echo "==> done: $MODEL_DIR"
ls -lh "$MODEL_DIR" | head -20
