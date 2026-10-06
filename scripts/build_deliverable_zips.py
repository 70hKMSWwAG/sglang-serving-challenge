# -*- coding: utf-8 -*-
"""重建两份交付 zip（UTF-8 文件名，跨平台）。

原仓库曾直接提交 HW2-0102603133.zip / HW3-0102603133.zip，其内容与对应
解包目录逐字节一致，为避免双份维护已从 git 移除；需要交付包时运行：

    python scripts/build_deliverable_zips.py

输出：
    dist/HW2-0102603133.zip   <- HW2/env-wsl/ 全部内容（平铺，与历史交付结构一致）
    dist/HW3-0102603133.zip   <- HW3/ray-serve-4gpu/ 全部内容（平铺）
"""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist")

JOBS = [
    ("HW2-0102603133.zip", os.path.join(ROOT, "HW2", "env-wsl")),
    ("HW3-0102603133.zip", os.path.join(ROOT, "HW3", "ray-serve-4gpu")),
]


def build(zip_name: str, src_dir: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, zip_name)
    n = 0
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(src_dir):
            dirnames.sort()
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, src_dir)
                zf.write(full, rel)  # 平铺结构，与历史交付一致
                n += 1
    print(f"{zip_name}: {n} files -> {dst}")


if __name__ == "__main__":
    for name, src in JOBS:
        build(name, src)
