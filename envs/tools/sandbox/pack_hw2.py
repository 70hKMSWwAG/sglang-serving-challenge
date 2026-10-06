#!/usr/bin/env python3
"""
打包 HW2 交付物为 HW2-<name>.zip，解压后仅包含同名根目录：
  HW2-<name>/{README.md, report.pdf, 作业感受.pdf, AI 使用说明情况（第二次挑战）.pdf,
             src/target1/, results/target1/, figures/, scripts/}

用法：python3 pack_hw2.py [姓名]
"""

import shutil
import sys
from pathlib import Path

SRC = Path("/workspace/HW2")
name = sys.argv[1] if len(sys.argv) > 1 else "姓名"
root_name = f"HW2-{name}"
TMP = Path("/workspace/_pack")
OUT = Path(f"/workspace/{root_name}.zip")

INCLUDE_FILES = [
    "README.md", "report.pdf", "作业感受.pdf", "AI 使用说明情况（第二次挑战）.pdf",
]
INCLUDE_DIRS = ["src", "results", "figures", "scripts"]
# 只打包流程图生成脚本：README 会引用它，避免解压后出现悬空引用
EXTRA_FILES = [("tools/gen_flowcharts.py", "tools/gen_flowcharts.py")]
EXCLUDE = {"__pycache__", "build", ".git", ".DS_Store", "*.pyc"}


def copy_filtered(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in EXCLUDE or item.suffix == ".pyc":
            continue
        if item.is_dir():
            copy_filtered(item, dst / item.name)
        else:
            shutil.copy2(item, dst / item.name)


def main():
    if TMP.exists():
        shutil.rmtree(TMP)
    target = TMP / root_name
    target.mkdir(parents=True)

    for f in INCLUDE_FILES:
        p = SRC / f
        if p.exists():
            shutil.copy2(p, target / f)
        else:
            print("MISSING:", f)
    for d in INCLUDE_DIRS:
        p = SRC / d
        if p.exists():
            copy_filtered(p, target / d)
        else:
            print("MISSING DIR:", d)

    for rel_src, rel_dst in EXTRA_FILES:
        p = Path("/workspace") / rel_src
        if p.exists():
            dst = target / rel_dst
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        else:
            print("MISSING:", rel_src)

    if OUT.exists():
        OUT.unlink()
    shutil.make_archive(OUT.with_suffix(""), "zip", TMP, root_name)
    print("packed:", OUT, f"{OUT.stat().st_size / 1024:.0f} KB")
    print("--- tree ---")
    for p in sorted(target.rglob("*")):
        if p.is_file():
            print("  ", p.relative_to(target))


if __name__ == "__main__":
    main()
