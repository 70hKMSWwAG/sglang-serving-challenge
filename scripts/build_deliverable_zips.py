# -*- coding: utf-8 -*-
"""重建两份作业交付 zip（UTF-8 文件名，跨平台）。

第三关要求（任务书「交付格式」）：在 github 上传 HW3-姓名（或学号）.zip，
**解压后仅包含同名根目录**，其内为 README.md / report.pdf / AI 使用说明情况.pdf /
src/ / results/。本脚本据此生成：

    HW3-0102603133.zip
    └── HW3-0102603133/
        ├── README.md
        ├── report.pdf
        ├── AI 使用说明情况（第三次挑战）.pdf
        ├── 作业感受（第三次挑战）.pdf
        ├── src/{target1,target3}/
        └── results/{target1,target3}/

运行：
    python scripts/build_deliverable_zips.py            # 生成 HW3 交付包

HW2-0102603133.zip 是 10-03 截止前提交的原版（提交 692995f），已冻结，本脚本不再重建它。
"""
import argparse
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (输出 zip 名, 源目录, zip 内顶层目录名)
JOBS = [
    ("HW3-0102603133.zip", os.path.join(ROOT, "HW3", "ray-serve-4gpu"), "HW3-0102603133"),
]
EXTRA_JOBS = []  # HW2 包已冻结（截止前原版），不再由脚本生成

SKIP_DIRS = {"__pycache__", ".ipynb_checkpoints", ".git"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def build(zip_name: str, src_dir: str, top_dir: str) -> None:
    dst = os.path.join(ROOT, zip_name)
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for dirpath, dirnames, filenames in os.walk(src_dir):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for fn in sorted(filenames):
                if any(fn.endswith(s) for s in SKIP_SUFFIX):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, src_dir).replace("\\", "/")
                arc = f"{top_dir}/{rel}" if top_dir else rel
                zf.write(full, arc)
                n += 1
    print(f"{zip_name}: {n} files, {os.path.getsize(dst)/1024/1024:.2f} MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="（已停用）HW2 包已冻结，不再生成")
    args = ap.parse_args()
    jobs = JOBS + (EXTRA_JOBS if args.all else [])
    for zip_name, src, top in jobs:
        build(zip_name, src, top)
