#!/bin/bash
# Fix TileLang's libcudart_stub.so for containers where the pip-installed
# libcudart is not globally visible in the way the stub expects.
#
# Root cause (2026-10-05):
#   SGLang 0.5.14 JIT-compiles CUDA kernels (rope, qk-norm, ...) via tvm-ffi.
#   The compiled kernels link against libcudart.so.11.0 (versioned symbols).
#   At runtime only pip's libcudart.so.13 exists, so TileLang's
#   libcudart_stub.so is used as a compatibility shim. Its TryLoadLibCudart()
#   does dlsym(RTLD_DEFAULT, "cudaGetErrorString") and aborts when the check
#   fails. The check is unreliable: when libcudart is preloaded with
#   RTLD_GLOBAL, symbol interposition makes the stub's own
#   &cudaGetErrorString resolve to the preloaded address, so the
#   "sym != &cudaGetErrorString" test fails and the process aborts with
#   "TileLang Error: libcudart symbols not found globally".
#
# Fix: recompile the stub from TileLang's own source with TryLoadLibCudart()
# trying explicit dlopen() paths first (pip nvidia packages), falling back
# to the original logic. The original .so is backed up.
#
# Usage: bash fix_tilelang_stub.sh
# Must run inside the sglang conda env (needs python to locate site-packages).
set -euo pipefail

SITE_PKGS="$(python -c 'import site; print(site.getsitepackages()[0])')"
STUB_DIR="${SITE_PKGS}/tilelang/lib"
STUB_SO="${STUB_DIR}/libcudart_stub.so"
SRC_CC="${SITE_PKGS}/tilelang/src/target/stubs/cudart.cc"

if [[ ! -f "${STUB_SO}" ]]; then
  echo "stub not found at ${STUB_SO}, skipping"
  exit 0
fi
if [[ ! -f "${SRC_CC}" ]]; then
  echo "stub source not found at ${SRC_CC}, skipping"
  exit 0
fi

# locate pip libcudart for the explicit dlopen list
CUDART_PATH="$(ls "${SITE_PKGS}"/nvidia/cu*/lib/libcudart.so.* 2>/dev/null | grep -E 'so\.[0-9]+$' | sort | tail -1 || true)"
if [[ -z "${CUDART_PATH}" ]]; then
  echo "no pip libcudart found, skipping"
  exit 0
fi
echo "using cudart: ${CUDART_PATH}"

# already fixed? check for our marker string in the binary
if strings "${STUB_SO}" | grep -q "TRY_EXPLICIT_DLOPEN_FIRST_20261005"; then
  echo "stub already fixed, skipping"
  exit 0
fi

cp "${STUB_SO}" "${STUB_SO}.bak.$(date +%Y%m%d)"
echo "backed up original stub"

WORK="$(mktemp -d)"
cp "${SRC_CC}" "${WORK}/cudart_fixed.cc"

python3 - <<PYEOF
p = "${WORK}/cudart_fixed.cc"
src = open(p).read()
old = "void *TryLoadLibCudart() {"
new = '''void *TryLoadLibCudart() {
  // TRY_EXPLICIT_DLOPEN_FIRST_20261005: explicit dlopen paths first, because
  // the RTLD_DEFAULT/RTLD_NEXT interposition check below is unreliable.
  {
    static const char *kPaths[] = {
        "${CUDART_PATH}",
        "libcudart.so.13",
        "libcudart.so.12",
        "libcudart.so",
    };
    for (size_t i = 0; i < sizeof(kPaths) / sizeof(kPaths[0]); ++i) {
      void *h = dlopen(kPaths[i], RTLD_NOW | RTLD_LOCAL);
      if (h != nullptr) {
        return h;
      }
    }
  }'''
assert old in src
open(p, "w").write(src.replace(old, new, 1))
print("source patched")
PYEOF

# need cuda_runtime_api.h; try common locations
INC=""
for d in "${CUDA_HOME:-/nonexistent}/include" /usr/local/cuda/include /root/cuda13_compat/include; do
  if [[ -f "$d/cuda_runtime_api.h" ]]; then INC="$d"; break; fi
done
if [[ -z "$INC" ]]; then
  # search site-packages nvidia cuda include
  INC="$(dirname "$(find "${SITE_PKGS}/nvidia" -name cuda_runtime_api.h 2>/dev/null | head -1)")" || true
fi
if [[ -z "$INC" || ! -f "$INC/cuda_runtime_api.h" ]]; then
  echo "cuda_runtime_api.h not found, cannot rebuild stub"
  exit 1
fi
echo "using CUDA headers: $INC"

g++ -shared -fPIC -O2 -std=c++17 -I"$INC" -o "${WORK}/libcudart_stub.so" "${WORK}/cudart_fixed.cc" -ldl
cp "${WORK}/libcudart_stub.so" "${STUB_SO}"
echo "fixed stub installed"
rm -rf "${WORK}"

# quick smoke test: the stub must resolve cudaGetErrorString without aborting
python3 - <<PYEOF
import ctypes
h = ctypes.CDLL("${STUB_SO}")
h.cudaGetErrorString.restype = ctypes.c_char_p
assert h.cudaGetErrorString(0) == b"no error", "stub smoke test failed"
print("stub smoke test passed")
PYEOF
