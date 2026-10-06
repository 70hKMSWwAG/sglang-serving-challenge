#!/usr/bin/env bash
#
# HW3 target3: create the two Python environments.
#
#   sglang-env : sglang[all]==0.5.14   (SGLang inference servers, needs GPU)
#   ray-env    : ray[serve]==2.56.0    (Ray Serve front-end + traffic generator)
#
# SGLang 0.5.14 requires Python >= 3.10 (see python/pyproject.toml at tag
# v0.5.14). The two envs stay separate on purpose: the Serve replicas talk to
# SGLang purely over HTTP, exactly as the assignment allows.
#
# Domestic mirrors are configured so installs work from mainland China.
# sglang[all] is a very large install (torch 2.11, flashinfer, ...); expect
# tens of minutes on first install.
#
set -euo pipefail

CONDA_BASE="${CONDA_BASE:-$HOME/miniconda3}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

if [ ! -x "$CONDA_BASE/bin/conda" ]; then
  echo "ERROR: conda not found at $CONDA_BASE/bin/conda" >&2
  echo "Install Miniconda first, or set CONDA_BASE to your conda prefix." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"

echo "==> configuring conda mirrors (tsinghua)"
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/ 2>/dev/null || true
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/ 2>/dev/null || true
conda config --set show_channel_urls yes 2>/dev/null || true

echo "==> creating sglang-env (python 3.12)"
if ! conda env list | grep -qE '^\s*sglang-env\s'; then
  conda create -y -n sglang-env python=3.12
fi
conda run -n sglang-env python -m pip install --upgrade pip -i "$PIP_INDEX"
echo "==> installing sglang[all]==0.5.14  (this takes a while)"
conda run -n sglang-env python -m pip install "sglang[all]==0.5.14" -i "$PIP_INDEX"
conda run -n sglang-env python -c "import sglang; print('sglang', sglang.__version__)"

echo "==> creating ray-env (python 3.10)"
if ! conda env list | grep -qE '^\s*ray-env\s'; then
  conda create -y -n ray-env python=3.10
fi
conda run -n ray-env python -m pip install --upgrade pip -i "$PIP_INDEX"
echo "==> installing ray[serve]==2.56.0 + httpx + aiohttp"
conda run -n ray-env python -m pip install "ray[serve]==2.56.0" httpx aiohttp -i "$PIP_INDEX"
# NOTE (2026-10-05): Ray 2.56.0's Serve needs protobuf with FieldDescriptor.label
# (removed in protobuf>=4 upb backend). Pin protobuf 4.25.9 +
# googleapis-common-protos 1.63.0, and run Serve with
# PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python (see run_round.sh).
conda run -n ray-env python -m pip install "protobuf==4.25.9" "googleapis-common-protos==1.63.0" -i "$PIP_INDEX"
conda run -n ray-env python -c "import ray; print('ray', ray.__version__)"

echo "==> fixing TileLang libcudart stub (container compat)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
conda run -n sglang-env bash "${SCRIPT_DIR}/fix_tilelang_stub.sh"

echo "==> done. Activate with: conda activate sglang-env | conda activate ray-env"
