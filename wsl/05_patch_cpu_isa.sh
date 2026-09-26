#!/usr/bin/env bash
# 05_patch_cpu_isa.sh —— 让 sgl-kernel 的 CPU 后端支持「无 AVX-512」的 x86_64 CPU
#
# 背景（上游限制，已在源码中核实）：
#   sgl-kernel/csrc/cpu/CMakeLists.txt 对所有 x86_64 目标无条件加入
#       -march=x86-64-v4  -mavx512bf16  -mavx512vnni  -mamx-tile/-bf16/-int8
#   即要求 AVX-512 + AMX。官方 docker/xeon.Dockerfile 面向的是 Intel Xeon
#   (Sapphire Rapids 及以上)，没有做运行时指令集分派。
#
#   csrc/cpu/vec.h 第 3-5 行据此推导：
#       #if defined(__AVX512F__) && defined(__AVX512BF16__) && defined(__AMX_BF16__)
#       #define CPU_CAPABILITY_AVX512
#       #endif
#   也就是说：只要不以 v4 编译，CPU_CAPABILITY_AVX512 自动不成立，
#   源码里所有 `#if defined(CPU_CAPABILITY_AVX512)` 的 AVX-512 快速路径
#   会被跳过，走 vec.h 中已有的通用回退实现（如 vec_reduce_sum/max 的 #else 分支）。
#
# 本脚本做的事：
#   1) 把该段 CMakeLists 改成「可由环境变量 SGLANG_CPU_ISA=baseline 切换到 AVX2 基线」，
#      默认行为不变（保持上游 v4），保证补丁是「增量、可解释、可回退」的；
#   2) 以 baseline 重新编译 sgl-kernel。
set -o pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/00_common.sh"

CML="${SRC}/sgl-kernel/csrc/cpu/CMakeLists.txt"
[ -f "$CML" ] || die "找不到 $CML（请先跑 01_setup_env.sh）"

log "==================== 阶段 1b/5：CPU ISA 兼容性补丁 ===================="

if grep -q 'SGLANG_CPU_ISA' "$CML"; then
  ok "补丁已存在，跳过"
else
  cp -n "$CML" "${CML}.orig"
  log "  备份原始文件 -> ${CML}.orig"

  # 用 Python 做精确的块替换，避免 sed 处理多行的脆弱性
  "${VENV}/bin/python" - "$CML" <<'PY'
import sys, re, pathlib
p = pathlib.Path(sys.argv[1])
s = p.read_text(encoding="utf-8")

old = '''if(MY_ARCH_DIR STREQUAL "x86_64")
    add_compile_options(
        -O3
        -Wno-unknown-pragmas
        -march=x86-64-v4
        -mavx512bf16
        -mavx512vnni
        -mamx-tile
        -mamx-bf16
        -mamx-int8
        -fopenmp
    )
else()'''

new = '''if(MY_ARCH_DIR STREQUAL "x86_64")
    # ---- [patched by 05_patch_cpu_isa.sh] ----
    # 上游默认强制 x86-64-v4 + AMX，只适用于支持 AVX-512 的 Intel Xeon
    # (Sapphire Rapids 及以上)。此处增加一个可选的 AVX2 基线分支，使 sgl-kernel
    # 也能在无 AVX-512 的消费级 x86_64 CPU 上运行。
    #   SGLANG_CPU_ISA=baseline  -> -march=x86-64-v3 (AVX2/FMA/BMI2)
    #   未设置或其它值           -> 保持上游 v4 行为
    if(DEFINED ENV{SGLANG_CPU_ISA} AND "$ENV{SGLANG_CPU_ISA}" STREQUAL "baseline")
        message(STATUS "SGLang CPU ISA: baseline (x86-64-v3, no AVX-512)")
        add_compile_options(
            -O3
            -Wno-unknown-pragmas
            -march=x86-64-v3
            -fopenmp
        )
    else()
        add_compile_options(
            -O3
            -Wno-unknown-pragmas
            -march=x86-64-v4
            -mavx512bf16
            -mavx512vnni
            -mamx-tile
            -mamx-bf16
            -mamx-int8
            -fopenmp
        )
    endif()
else()'''

if old not in s:
    sys.exit("补丁失败：未能在 CMakeLists.txt 中定位原始代码块")
p.write_text(s.replace(old, new, 1), encoding="utf-8")
print("  ✓ CMakeLists.txt 已打补丁")
PY
  [ $? -eq 0 ] || die "补丁失败"
fi

# ---------- 重新编译 ----------
log "以 AVX2 基线重新编译 sgl-kernel（约 1~5 分钟）"
cd "${SRC}/sgl-kernel" || die "cd sgl-kernel 失败"
cp -f pyproject_cpu.toml pyproject.toml

# 先卸载旧的（含 AVX-512 的）产物，避免 import 命中缓存的坏 .so
uv pip uninstall --python "${VENV}/bin/python" sgl-kernel sgl_kernel 2>/dev/null | tail -2 || true

SGLANG_CPU_ISA=baseline \
VIRTUAL_ENV="${VENV}" CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" \
  uv pip install --python "${VENV}/bin/python" --no-build-isolation --no-deps --reinstall . 2>&1 | tail -18 \
  || die "sgl-kernel 基线重编译失败"

ok "编译完成，开始验证"

# ---------- 验证：能 import 且不再 SIGILL ----------
log "验证 sgl_kernel 可加载"
if "${VENV}/bin/python" - <<'PY'
import sgl_kernel, torch
print("  ✓ sgl_kernel 导入成功:", sgl_kernel.__file__)
print("  ✓ torch:", torch.__version__)
PY
then
  ok "sgl-kernel 基线版本可用"
else
  die "sgl_kernel 仍不可用"
fi

log "==================== ISA 补丁阶段完成 ===================="
