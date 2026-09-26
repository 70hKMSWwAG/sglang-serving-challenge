#!/usr/bin/env bash
# 快速自检：sglang / sgl_kernel / torch 是否可用
VENV=/opt/sgl-workspace/.venv
cd /opt/sgl-workspace/sglang || exit 1
export SGLANG_USE_CPU_ENGINE=1

echo "=== python ==="
"$VENV/bin/python" -V

echo "=== import torch ==="
"$VENV/bin/python" - <<'PY'
import torch
print("torch:", torch.__version__)
print("threads:", torch.get_num_threads())
PY

echo "=== import sgl_kernel ==="
"$VENV/bin/python" - <<'PY'
try:
    import sgl_kernel
    print("sgl_kernel OK ->", getattr(sgl_kernel, "__file__", "?"))
except Exception as e:
    print("sgl_kernel FAIL:", type(e).__name__, e)
PY

echo "=== import sglang ==="
"$VENV/bin/python" - <<'PY'
try:
    import sglang
    print("sglang OK ->", getattr(sglang, "__file__", "?"))
    print("version:", getattr(sglang, "__version__", "n/a"))
except Exception as e:
    import traceback; traceback.print_exc()
PY
