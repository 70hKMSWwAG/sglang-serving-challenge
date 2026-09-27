#!/usr/bin/env bash
# =============================================================================
# 07_probe_gpu.sh —— 探测 WSL 内 Intel Arc B370 核显能否用于 AI 推理
#
# 说明：本脚本会尝试加载 vgem 模块（只往内核插一个模块，重启即失效、
#       不改任何配置文件），其余步骤全部只读。不会安装任何软件包。
# 用法： bash /mnt/d/first-task/wsl/07_probe_gpu.sh 2>&1 | tee /mnt/d/first-task/work/gpu_probe.txt
#
# 第二轮实测（2026-09-27 18:25）结论已固化在 evidence/11_gpu_probe_sudo.txt。
# =============================================================================

set -o pipefail

# sudo 前缀：能免密就用，否则尝试交互；都没有则空跑
if [ "$(id -u)" = "0" ]; then SUDO=""
elif command -v sudo >/dev/null 2>&1; then SUDO="sudo"
else SUDO=""
fi

echo "==================== WSL 内 Intel GPU 可用性探测 ===================="
date '+%F %T'
echo

# ------------------------------------------------- 1. 真实 Intel DRM 驱动是否加载
echo "--- [0] Intel 内核 DRM 驱动 / 模块 ---"
for m in i915 xe; do
  if [ -d "/sys/module/$m" ]; then echo "  已加载  $m"; else echo "  未加载  $m"; fi
done
echo

# ---------------------------------------------------------------- 2. 设备节点
echo "--- [1] DRM 设备节点 /dev/dri ---"
if [ ! -d /dev/dri ]; then
  echo "/dev/dri 不存在 —— 尝试加载 vgem（需 root 权限，缺 sudo 会报 Operation not permitted）"
  $SUDO modprobe vgem 2>&1 | head -3
fi

if [ -d /dev/dri ]; then
  ls -la /dev/dri
  echo
  echo "  节点归属判定（关键：/dev/dri 存在 ≠ 有 GPU）:"
  for n in /sys/class/drm/card*/device/driver; do
    [ -e "$n" ] || continue
    dev=$(echo "$n" | cut -d/ -f5)
    drv=$(basename "$(readlink -f "$n")")
    echo "    $dev 由驱动 '$drv' 提供"
  done
  echo "    dmesg 中的初始化记录:"
  $SUDO dmesg 2>/dev/null | grep -iE 'initialized .*(drm|vgem|i915|xe)' | tail -6 | sed 's/^/      /'
  echo
  echo "  判定：若驱动为 vgem / platform → 这是**虚拟软件桩**，不能用于计算；"
  echo "        只有出现 i915 / xe 才是真实 Intel 核显。"
else
  echo "结论: 仍然没有 /dev/dri"
fi
echo

echo "--- [2] DirectX 直通设备 /dev/dxg ---"
if [ -e /dev/dxg ]; then
  ls -la /dev/dxg
  echo "结论: /dev/dxg 存在（Windows 侧 dxgkrnl 已把 GPU 暴露给 WSL）"
else
  echo "结论: /dev/dxg 不存在"
fi
echo

# ------------------------------------------------------- 3. Windows 侧驱动文件
echo "--- [3] /usr/lib/wsl/lib（WSL 侧的 D3D12 翻译库目录）---"
if [ -d /usr/lib/wsl/lib ]; then
  ls /usr/lib/wsl/lib | head -25
  n=$(ls /usr/lib/wsl/lib 2>/dev/null | wc -l)
  echo "文件数: $n"
  for f in libdxcore.so libd3d12.so libd3d12core.so libwsl_compute_helper.so; do
    if [ -e "/usr/lib/wsl/lib/$f" ]; then echo "  有   $f"; else echo "  缺   $f"; fi
  done
else
  echo "/usr/lib/wsl/lib 不存在"
fi
echo

# ------------------------------------------------------------- 4. 用户组与内核
echo "--- [4] 当前用户与内核 ---"
echo "whoami : $(whoami)"
echo "groups : $(groups)"
echo "kernel : $(uname -r)"
echo "vgem   : $(lsmod 2>/dev/null | grep -c '^vgem' ) (1=已加载)"
echo

# --------------------------------------------------------- 5. 计算运行时（用户态）
echo "--- [5] Intel 计算运行时是否已安装 ---"
for c in clinfo sycl-ls xpu-smi level-zero; do
  p=$(command -v "$c" 2>/dev/null)
  if [ -n "$p" ]; then echo "  有   $c -> $p"; else echo "  缺   $c"; fi
done
echo
echo "  OpenCL ICD 列表:"
ls /etc/OpenCL/vendors/ 2>/dev/null | sed 's/^/    /' || echo "    (无 /etc/OpenCL/vendors)"
echo
echo "  Level-Zero 库:"
ls /usr/lib/x86_64-linux-gnu/ 2>/dev/null | grep -iE 'libze_|libze1' | sed 's/^/    /' || echo "    (未找到 libze*)"
echo

# ---------------------------------------------------------------- 6. 内核日志线索
echo "--- [6] dmesg 中的 GPU 线索（若可读）---"
($SUDO dmesg 2>/dev/null | grep -iE 'dxg|vgem|drm|i915|xe ' | tail -12) || echo "(dmesg 不可读)"
echo
echo "  -22 = EINVAL。dxgkio_query_adapter_info 持续失败，说明 WSL 的 dxgkrnl"
echo "  与 Windows 显卡驱动之间的适配器查询并未走通。"
echo

# -------------------------------------------------------------------- 7. 结论
echo "==================== 判定 ===================="
REAL_DRV=""
for m in i915 xe; do
  [ -d "/sys/module/$m" ] && REAL_DRV="$m"
done
HAS_CRT=0
command -v clinfo >/dev/null 2>&1 && HAS_CRT=1

if [ -n "$REAL_DRV" ] && [ -e /dev/dxg ]; then
  echo "GPU 直通【可用】：真实 Intel DRM 驱动 ($REAL_DRV) 已加载 → 可继续评估 XPU 路线"
elif [ -d /dev/dri ] && [ -z "$REAL_DRV" ]; then
  echo "GPU 计算【不可用】：/dev/dri 下的节点来自 vgem 虚拟桩（无 i915/xe），不能计算"
  echo "  且计算运行时$([ $HAS_CRT = 1 ] && echo '存在' || echo '缺失')、dxgkrnl 握手报 EINVAL。"
  echo "  → 纯 CPU 推理的路线选择成立，不建议再投入 XPU 重编译。"
elif [ -e /dev/dxg ]; then
  echo "GPU 部分可用：/dev/dxg 在但 /dev/dri 缺 → 无真实 Intel DRM 驱动"
else
  echo "GPU 直通【不可用】：/dev/dxg 缺失 → 需在 Windows 侧重装/更新 Intel 显卡驱动"
fi
echo "============================================="
