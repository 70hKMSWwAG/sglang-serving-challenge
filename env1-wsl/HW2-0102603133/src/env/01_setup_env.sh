#!/usr/bin/env bash
# 01_setup_env.sh —— 一键搭建 SGLang 0.5.14 CPU 推理环境 + Ray 2.56.0 独立环境
#
# 在 WSL 内执行：
#   sudo bash /mnt/d/first-task/wsl/01_setup_env.sh
# 或以 root 身份（推荐，免密码）：
#   wsl -u root -e bash /mnt/d/first-task/wsl/01_setup_env.sh
#
# 该脚本幂等，可重复执行。所有产物落在 /mnt/d/first-task/work/ 下。
# 对齐官方 docker/xeon.Dockerfile 的 CPU 配方。
set -o pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=00_common.sh
source "$HERE/00_common.sh"

log "==================== 阶段 1/5：环境与构建 ===================="

# ---------- 1.1 硬件/系统报告 ----------
{
  echo "### uname"; uname -a
  echo "### os-release"; cat /etc/os-release 2>/dev/null | head -4
  echo "### cpu"; lscpu 2>/dev/null | grep -Ei 'model name|^cpu\(s\)|thread|core|numa|socket|flags' | head -12
  echo "### mem"; free -h 2>/dev/null
  echo "### disk(/)"; df -h / /opt 2>/dev/null
  echo "### gcc"; gcc --version 2>/dev/null | head -1
} | tee "${LOGD}/00_env_report.log"
ok "环境报告已写入 ${LOGD}/00_env_report.log"

if ! $SUDO -n true 2>/dev/null && [ "$(id -u)" -ne 0 ]; then
  warn "当前用户无免密 sudo。若卡在密码提示，请改用: sudo bash $0"
fi

# ---------- 1.2 apt 依赖（逐个装，缺哪个装哪个） ----------
log "步骤 1.2 安装系统依赖"
$SUDO apt-get update -qq 2>&1 | tail -2 || warn "apt-get update 失败，继续尝试"
for p in ca-certificates git curl wget build-essential gcc g++ make cmake ninja-build \
         pkg-config libsqlite3-dev libnuma-dev numactl libtbb-dev \
         libgoogle-perftools-dev google-perftools zlib1g-dev libomp-dev; do
  apt_ensure "$p"
done

# ---------- 1.3 uv + Python 3.12 ----------
log "步骤 1.3 准备 uv 与 Python ${PY_VER}（与发行版解耦）"
export PATH="$HOME/.local/bin:/root/.local/bin:$PATH"
export UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-/opt/uv-python}"

if ! command -v uv >/dev/null 2>&1; then
  log "  尝试官方脚本安装 uv"
  curl -LsSf --connect-timeout 25 https://astral.sh/uv/install.sh 2>/dev/null | sh >/dev/null 2>&1 || true
  export PATH="$HOME/.local/bin:/root/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
  warn "官方脚本失败，尝试从 GitHub Release 镜像下载 uv"
  mkdir -p /opt/uvbin && cd /opt/uvbin
  if fetch "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz" uv.tgz; then
    tar xzf uv.tgz --strip-components=1 && cp -f uv uvx /usr/local/bin/ 2>/dev/null
    export PATH="/usr/local/bin:$PATH"
  fi
fi
command -v uv >/dev/null 2>&1 && ok "uv: $(uv --version)" || die "uv 安装失败"

mkdir -p "$ROOT"

# 【本地优先】Windows 侧已预取 standalone CPython，直接解压 —— 完全不依赖 GitHub
PYBIN=""
if [ -f "$CPY_TAR" ]; then
  if [ ! -x "${PYROOT}/python/bin/python3" ]; then
    log "  解压本地 CPython 包: $CPY_TAR"
    rm -rf "$PYROOT"; mkdir -p "$PYROOT"
    tar xzf "$CPY_TAR" -C "$PYROOT" || warn "CPython 解压失败，转 uv 在线下载"
  fi
  PYBIN=$(ls "${PYROOT}/python/bin/python3.${PY_VER#3.}" "${PYROOT}/python/bin/python3" 2>/dev/null | head -1)
  [ -n "$PYBIN" ] && ok "本地 CPython: $("$PYBIN" -V 2>&1)"
fi

if [ ! -x "${VENV}/bin/python" ]; then
  if [ -n "$PYBIN" ]; then
    uv venv --python "$PYBIN" "$VENV" 2>&1 | tail -3 || die "venv 创建失败（本地 Python）"
  elif ! uv venv --python "$PY_VER" "$VENV" 2>&1 | tail -3; then
    warn "直连下载 Python 失败，切镜像"
    export UV_PYTHON_INSTALL_MIRROR="https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download"
    uv venv --python "$PY_VER" "$VENV" 2>&1 | tail -3 || die "venv 创建失败"
  fi
fi
ok "venv python: $("${VENV}/bin/python" -V 2>&1)"

# ---------- 1.4 取 SGLang 源码 v0.5.14 ----------
log "步骤 1.4 获取 SGLang 源码 ${SGL_VER}"
if [ ! -f "${SRC}/python/pyproject_cpu.toml" ]; then
  rm -rf "$SRC"
  # 【本地优先】使用 Windows 侧预取的源码快照
  if [ -f "$SGL_TAR" ]; then
    log "  【本地】解压预取源码包: $SGL_TAR"
    mkdir -p "$SRC" && tar xzf "$SGL_TAR" -C "$SRC" --strip-components=1 \
      && ok "本地源码包解压完成" || { warn "本地源码包损坏，转网络获取"; rm -rf "$SRC"; }
  fi
  if [ ! -f "${SRC}/python/pyproject_cpu.toml" ]; then
    if git clone --depth 1 --branch "$SGL_VER" https://github.com/sgl-project/sglang.git "$SRC" 2>&1 | tail -3 \
       && [ -f "${SRC}/python/pyproject_cpu.toml" ]; then
      ok "git clone 成功（${SGL_VER}）"
    else
      warn "git clone 失败，改用 codeload 快照"
      rm -rf "$SRC" /tmp/sgl.tgz
      curl -fsSL --connect-timeout 25 --max-time 900 \
        -o /tmp/sgl.tgz "https://codeload.github.com/sgl-project/sglang/tar.gz/refs/tags/${SGL_VER}" \
        || fetch "https://github.com/sgl-project/sglang/archive/refs/tags/${SGL_VER}.tar.gz" /tmp/sgl.tgz \
        || die "源码下载失败"
      mkdir -p "$SRC" && tar xzf /tmp/sgl.tgz -C "$SRC" --strip-components=1
    fi
  fi
fi
[ -f "${SRC}/python/pyproject_cpu.toml" ] || die "源码目录异常：找不到 python/pyproject_cpu.toml"
ok "源码就绪: ${SRC}  (pyproject_cpu.toml 存在)"

# ---------- 1.5 关键：torch 系指向 CPU 索引，避免拉 10GB CUDA 依赖 ----------
log "步骤 1.5 写 uv 索引配置（torch CPU）"
cat > "${VENV}/uv.toml" <<'EOF'
[[index]]
name = "torch"
url = "https://download.pytorch.org/whl/cpu"

[[index]]
name = "torchvision"
url = "https://download.pytorch.org/whl/cpu"

[[index]]
name = "torchaudio"
url = "https://download.pytorch.org/whl/cpu"

[[index]]
name = "triton"
url = "https://download.pytorch.org/whl/cpu"
EOF
export UV_CONFIG_FILE="${VENV}/uv.toml"
ok "UV_CONFIG_FILE=${UV_CONFIG_FILE}"

# ---------- 1.6 安装 sglang-cpu 主包（这会编译/安装 torch 2.12.0+cpu 等） ----------
log "步骤 1.6 安装 sglang-cpu 主包（耗时较长，约 5~15 分钟）"
cd "${SRC}/python" || die "cd python 失败"
cp -f pyproject_cpu.toml pyproject.toml
if ! uv pip install --python "${VENV}/bin/python" . 2>&1 | tail -20; then
  die "sglang-cpu 主包安装失败"
fi
"${VENV}/bin/python" -c "import torch,transformers;print('  torch',torch.__version__);print('  transformers',transformers.__version__)" \
  || warn "torch/transformers 导入异常"

# ---------- 1.7 编译 sgl-kernel CPU 后端（原生 C++，约 10~40 分钟） ----------
log "步骤 1.7 编译 sgl-kernel CPU 后端（耗时最长，请耐心）"
# 幂等守卫：本步骤极慢，若已安装成功则直接跳过（除非 FORCE_KERNEL=1）
if [ "${FORCE_KERNEL:-0}" != "1" ] && \
   "${VENV}/bin/python" -c "import sgl_kernel" >/dev/null 2>&1; then
  ok "sgl-kernel 已安装，跳过编译（FORCE_KERNEL=1 可强制重建）"
elif [ "${CPU_HAS_AVX512:-1}" = "0" ]; then
  warn "本机 CPU 无 AVX-512：上游 v0.5.14 的 CPU 后端默认以 x86-64-v4+AMX 编译，"
  warn "在该类 CPU 上 import 会直接 Illegal instruction。改用 AVX2 基线编译。"
  bash "$HERE/05_patch_cpu_isa.sh" || die "AVX2 基线编译失败"
else
  uv pip install --python "${VENV}/bin/python" "scikit-build-core>=0.10" wheel ninja cmake 2>&1 | tail -3
  cd "${SRC}/sgl-kernel" || die "cd sgl-kernel 失败"
  cp -f pyproject_cpu.toml pyproject.toml
  # setuptools/cmake 会读取 VIRTUAL_ENV 来找 venv 的 lib 与 include
  VIRTUAL_ENV="${VENV}" CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" \
    uv pip install --python "${VENV}/bin/python" --no-build-isolation . 2>&1 | tail -25 \
    || warn "sgl-kernel 编译失败（部分场景可用，继续）"
fi

# ---------- 1.8 Ray 2.56.0 独立环境（与 SGLang 分离，HTTP 通信） ----------
log "步骤 1.8 创建 Ray ${RAY_VER} 独立环境"
# 注意：绝不能沿用上面为 torch 设定的 UV_CONFIG_FILE —— 它把包解析限制在
# PyTorch 的 CPU 索引上，会让 ray 的依赖（packaging 等）判定为无解。
unset UV_CONFIG_FILE
unset UV_INDEX UV_INDEX_URL UV_EXTRA_INDEX_URL UV_DEFAULT_INDEX 2>/dev/null || true
if [ ! -x "${RAYVENV}/bin/python" ]; then
  uv venv --python "$PY_VER" "$RAYVENV" 2>&1 | tail -2
fi
if ! uv pip install --python "${RAYVENV}/bin/python" "ray==${RAY_VER}" \
       --index-strategy unsafe-best-match 2>&1 | tail -8; then
  warn "ray 安装失败"
fi
"${RAYVENV}/bin/python" -c "import ray;print('  ray',ray.__version__)" 2>/dev/null && ok "Ray ${RAY_VER} 就绪" || warn "ray 未就绪"

# ---------- 1.9 下载模型 Qwen/Qwen3-0.6B ----------
log "步骤 1.9 准备模型 ${MODEL_ID}"
if [ -f "${MODEL_DIR}/config.json" ]; then
  ok "模型已就绪，跳过"
else
  mkdir -p "$(dirname "$MODEL_DIR")"
  # 【本地优先】直接复制 Windows 侧已下载的权重（避免 WSL 访问 HuggingFace）
  if [ -f "${PREM}/Qwen3-0.6B/config.json" ]; then
    log "  【本地】复制预取模型 ${PREM}/Qwen3-0.6B -> ${MODEL_DIR}"
    cp -r "${PREM}/Qwen3-0.6B" "$MODEL_DIR" && ok "本地模型复制完成"
  fi
  if [ ! -f "${MODEL_DIR}/config.json" ]; then
    if "${VENV}/bin/modelscope" download --model "$MODEL_ID" --local_dir "$MODEL_DIR" 2>&1 | tail -5; then
      ok "ModelScope 下载完成"
    else
      warn "ModelScope 失败，改用 HF 镜像 (hf-mirror.com)"
      HF_ENDPOINT="https://hf-mirror.com" "${VENV}/bin/python" - <<PY 2>&1 | tail -5
from huggingface_hub import snapshot_download
p = snapshot_download("${MODEL_ID}", local_dir="${MODEL_DIR}")
print("downloaded to", p)
PY
    fi
  fi
fi
[ -f "${MODEL_DIR}/config.json" ] && ok "模型就绪: ${MODEL_DIR}" || die "模型下载失败"

# ---------- 1.10 落地环境文件，供后续脚本 source ----------
LD_PRELOAD_VAL="$(build_ld_preload)"
cat > "${OUTD}/env.sh" <<EOF
# 由 01_setup_env.sh 生成 $(date -Is)
export SGL_VER="${SGL_VER}"
export RAY_VER="${RAY_VER}"
export PY_VER="${PY_VER}"
export MODEL_ID="${MODEL_ID}"
export WORK="${WORK}"
export ROOT="${ROOT}"
export SRC="${SRC}"
export VENV="${VENV}"
export RAYVENV="${RAYVENV}"
export MODEL_DIR="${MODEL_DIR}"
export HOST="${HOST}"
export PORT="${PORT}"
export BASE="${BASE}"
export OUTD="${OUTD}"
export LOGD="${LOGD}"
export RESD="${RESD}"
export DATD="${DATD}"
export TRACE_FILE="${TRACE_LOCAL}"
export SGLANG_USE_CPU_ENGINE=1
export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
export LD_PRELOAD="${LD_PRELOAD_VAL}"
EOF
log "LD_PRELOAD = ${LD_PRELOAD_VAL:-<空>}"
ok "环境文件: ${OUTD}/env.sh"

log "==================== 构建阶段完成 ===================="
echo "下一步: bash ${WSLD}/02_start_server.sh"
