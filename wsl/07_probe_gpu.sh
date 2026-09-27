#!/usr/bin/env bash
# =============================================================================
# 07_probe_gpu.sh —— 探测 WSL 内 Intel Arc B370 核显的可用性
#
# 只读探测，不安装任何东西、不改任何配置。用于判断「能否走 SGLang XPU 路线」。
# 用法： bash /mnt/d/first-task/wsl/07_probe_gpu.sh
# =============================================================================

set -o pipefail

echo "==================== WSL 内 Intel GPU 可用性探测 ===================="
date '+%F %T'
echo

# ---------------------------------------------------------------- 1. 设备节点
echo "--- [1] DRM 设备节点 /dev/dri ---"
if [ -d /dev/dri ]; then
  ls -la /dev/dri
  echo "结论: /dev/dri 存在"
else
  echo "/dev/dri 不存在"
  echo "尝试加载 vgem 模块（Intel 官方 WSL 指南要求在缺失时执行）..."
  modprobe vgem 2>&1 | head -3
  if [ -d /dev/dri ]; then
    ls -la /dev/dri
    echo "结论: modprobe vgem 后 /dev/dri 出现"
  else
    echo "结论: 仍然没有 /dev/dri —— WSL 侧拿不到 GPU"
  fi
fi
echo

echo "--- [2] DirectX 直通设备 /dev/dxg ---"
if [ -e /dev/dxg ]; then
  ls -la /dev/dxg
  echo "结论: /dev/dxg 存在（说明 Windows 侧 dxgkrnl 已把 GPU 暴露给 WSL）"
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
(dmesg 2>/dev/null | grep -iE 'dxg|vgem|drm|i915|xe ' | tail -12) || echo "(dmesg 不可读，需要 root)"
echo

# -------------------------------------------------------------------- 7. 结论
echo "==================== 判定 ===================="
if [ -e /dev/dxg ] && [ -d /dev/dri ]; then
  echo "GPU 直通【可用】→ 可以继续尝试 SGLang XPU 路线"
elif [ -e /dev/dxg ]; then
  echo "GPU 部分可用：/dev/dxg 在但 /dev/dri 缺 → 先 modprobe vgem，或装 Intel 计算运行时"
else
  echo "GPU 直通【不可用】：/dev/dxg 缺失 → 需在 Windows 侧重装/更新 Intel 显卡驱动"
  echo "  若 /dev/dxg 在而 /dev/dri 缺：缺的是 DRM 节点与计算运行时，"
  echo "  应装 Intel 的 WSL 计算组件（Level-Zero / OpenCL），不是重装显卡驱动。"
fi
echo "============================================="
