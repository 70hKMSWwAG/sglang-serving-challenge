#!/usr/bin/env bash
# 00_common.sh —— 公共配置与工具函数（被其它脚本 source）
# 设计原则：容错优先、幂等、绝不因为一个可选依赖让整个流程白跑。

# ---------------- 版本与环境（与挑战要求严格对齐） ----------------
SGL_VER="${SGL_VER:-v0.5.14}"          # SGLang 0.5.14
RAY_VER="${RAY_VER:-2.56.0}"           # Ray 2.56.0
PY_VER="${PY_VER:-3.12}"               # SGLang/Ray 官方 CPU 配方使用 3.12
MODEL_ID="${MODEL_ID:-Qwen/Qwen3-0.6B}" # 要求使用的模型

# ---------------- 路径（全部放在 /mnt/d 下，Windows 侧可直接读） ----------------
WORK="${WORK:-/mnt/d/first-task}"      # Windows D:\first-task
WSLD="${WORK}/wsl"
OUTD="${WORK}/work"                    # 运行产物：日志 / 指标 / trace
LOGD="${OUTD}/logs"
RESD="${OUTD}/results"
DATD="${OUTD}/data"

ROOT="${SGL_ROOT:-/opt/sgl-workspace}" # 构建根目录
SRC="${ROOT}/sglang"                   # SGLang 源码
VENV="${ROOT}/.venv"                   # SGLang 0.5.14 (CPU) 环境
RAYVENV="${ROOT}/ray-venv"             # Ray 2.56.0 独立环境（与 SGLang 隔离，HTTP 通信）
MODEL_DIR="${ROOT}/models/Qwen3-0.6B"  # 模型缓存

# ---------------- Windows 侧已预取的大文件（WSL 无需访问 GitHub/HF） ----------------
PRE="${WORK}/data"                     # mooncake trace / sglang 源码包 / CPython 包
PREM="${WORK}/models"                  # 预取的模型权重
CPY_TAR="${PRE}/cpython-3.12-linux-x86_64.tar.gz"
SGL_TAR="${PRE}/sglang-v0.5.14.tar.gz"
TRACE_LOCAL="${PRE}/mooncake_trace.jsonl"
PYROOT="${PYROOT:-/opt/py312}"         # standalone CPython 解压位置

HOST="${SGL_HOST:-127.0.0.1}"
PORT="${SGL_PORT:-30000}"
BASE="http://${HOST}:${PORT}"

# ---------------- CPU 指令集探测 ----------------
# 上游 sgl-kernel/csrc/cpu/CMakeLists.txt 对 x86_64 无条件启用 x86-64-v4 + AMX，
# 只有支持 AVX-512 的 Intel Xeon(Sapphire Rapids+) 能运行。这里做一次探测，
# 决定是否需要走「AVX2 基线」编译（详见 05_patch_cpu_isa.sh）。
if grep -qm1 'avx512f' /proc/cpuinfo 2>/dev/null; then
  CPU_HAS_AVX512=1
else
  CPU_HAS_AVX512=0
fi
export CPU_HAS_AVX512

mkdir -p "$LOGD" "$RESD" "$DATD" "$ROOT"

# ---------------- 日志 ----------------
log()  { printf '\n\033[1;36m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\n\033[1;33m[WARN %s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
die()  { printf '\n\033[1;31m[FAIL %s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; exit 1; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }

# ---------------- sudo ----------------
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

# ---------------- PATH：uv 由官方脚本装到 ~/.local/bin，需手动纳入 ----------------
# 各脚本是独立进程（05 会被 01 直接调用），必须在公共库统一设置，
# 否则子脚本里会出现 "uv: command not found"。
export PATH="${HOME}/.local/bin:/root/.local/bin:/usr/local/bin:${PATH}"
if ! command -v uv >/dev/null 2>&1; then
  for cand in /root/.local/bin/uv "${HOME}/.local/bin/uv" /usr/local/bin/uv /opt/uvbin/uv; do
    [ -x "$cand" ] && { export PATH="$(dirname "$cand"):${PATH}"; break; }
  done
fi

# ---------------- apt（逐个安装，避免一个包名不存在导致整条失败） ----------------
apt_ensure() {
  local pkg="$1"
  if dpkg -s "$pkg" >/dev/null 2>&1; then
    ok "apt 已安装: $pkg"
    return 0
  fi
  if $SUDO apt-get install -y --no-install-recommends "$pkg" >/dev/null 2>&1; then
    ok "apt 新装: $pkg"
  else
    warn "apt 装不上（忽略继续）: $pkg"
  fi
}

# 在系统里找第一个存在的库文件
first_exist() {
  local f
  for f in "$@"; do
    [ -e "$f" ] && { echo "$f"; return 0; }
  done
  return 1
}

# ---------------- 组装 LD_PRELOAD（逐库探测，绝不硬编码） ----------------
build_ld_preload() {
  local libs=()
  local tcmalloc tbb iomp
  tcmalloc=$(first_exist /usr/lib/x86_64-linux-gnu/libtcmalloc.so.4 \
                         /usr/lib/x86_64-linux-gnu/libtcmalloc.so \
                         /usr/lib/x86_64-linux-gnu/libtcmalloc_minimal.so.4) || true
  tbb=$(first_exist /usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2 \
                    /usr/lib/x86_64-linux-gnu/libtbbmalloc.so) || true
  iomp=$(find "$VENV" -name 'libiomp5.so' 2>/dev/null | head -1) || true
  [ -n "$tcmalloc" ] && libs+=("$tcmalloc")
  [ -n "$tbb" ]      && libs+=("$tbb")
  [ -n "$iomp" ]     && libs+=("$iomp")
  if [ "${#libs[@]}" -gt 0 ]; then
    local IFS=:
    echo "${libs[*]}"
  fi
}

# ---------------- 下载（带镜像回退） ----------------
# 说明：统一用 curl，不用 python urllib —— 代理做 TLS 中间人时
# curl 走系统证书库（Schannel）反而可用。
fetch() {
  local url="$1" out="$2"
  local try
  for try in "$url" \
             "https://gh-proxy.com/$url" \
             "https://gh.ddlc.top/$url"; do
    if curl -fsSL --connect-timeout 25 --max-time 600 -o "$out" "$try" 2>/dev/null; then
      if [ -s "$out" ]; then ok "下载成功: $try"; return 0; fi
    fi
  done
  return 1
}

# ---------------- 服务健康检查 ----------------
wait_ready() {
  local timeout="${1:-900}" t=0
  log "等待 SGLang 服务就绪（最长 ${timeout}s）: ${BASE}/v1/models"
  while [ "$t" -lt "$timeout" ]; do
    if curl -s --noproxy '*' --max-time 5 "${BASE}/v1/models" 2>/dev/null | grep -q '"id"'; then
      ok "服务已就绪（耗时 ${t}s）"
      return 0
    fi
    sleep 5; t=$((t+5))
    [ $((t % 60)) -eq 0 ] && printf '  ...已等待 %ss\n' "$t"
  done
  return 1
}
