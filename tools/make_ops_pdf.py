#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_ops_pdf.py —— 把若干张终端截图拼成一份 A4 的「操作保存.pdf」。

排版原则
--------
* 每张截图独占一节：节标题 + 说明 + 等比缩放后的截图；
* 单张截图过高时自动缩放以适配页面，绝不让内容被裁切；
* 使用 PyMuPDF 直接排版，不经过 HTML，避免二次缩放造成的模糊。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymupdf

A4 = pymupdf.paper_rect("a4")
MARGIN = 42.0
GAP = 14.0


def fit(img_path: Path, max_w: float, max_h: float):
    """返回按比例缩放后的 (rect_width, rect_height)。"""
    pix = pymupdf.Pixmap(str(img_path))
    w, h = pix.width, pix.height
    scale = min(max_w / w, max_h / h)
    return w * scale, h * scale


def build(sections, out_pdf: Path):
    doc = pymupdf.open()
    page_w = A4.width
    page_h = A4.height
    content_w = page_w - 2 * MARGIN
    content_h = page_h - 2 * MARGIN

    page = doc.new_page(width=page_w, height=page_h)
    y = MARGIN

    def new_page():
        nonlocal page, y
        page = doc.new_page(width=page_w, height=page_h)
        y = MARGIN

    for idx, (title, caption, img) in enumerate(sections, 1):
        img = Path(img)
        if not img.exists():
            print(f"[warn] 跳过不存在的截图: {img}", file=sys.stderr)
            continue

        # 预留：标题(约22) + 说明行(自动) + 间距
        cap_lines = 0
        if caption:
            cap_lines = max(1, int(len(caption) / 62) + 1)
        block_head = 24 + cap_lines * 13 + 6

        avail_h = content_h - block_head
        if avail_h < 80:                      # 页面剩余空间不足，换页
            new_page()
            avail_h = content_h - block_head

        iw, ih = fit(img, content_w, avail_h)

        if y + block_head + ih > page_h - MARGIN:
            new_page()

        # 节标题
        page.insert_text((MARGIN, y + 13), f"{idx}. {title}",
                         fontname="china-s", fontsize=13.5, color=(0.05, 0.11, 0.28))
        y += 22
        if caption:
            rc = pymupdf.Rect(MARGIN, y, page_w - MARGIN, y + cap_lines * 13 + 4)
            page.insert_textbox(rc, caption, fontname="china-s", fontsize=9.2,
                                color=(0.29, 0.35, 0.44), align=0)
            y += cap_lines * 13 + 6

        # 截图（居中）
        x0 = MARGIN + (content_w - iw) / 2
        rect = pymupdf.Rect(x0, y, x0 + iw, y + ih)
        page.insert_image(rect, filename=str(img))
        # 细边框
        page.draw_rect(rect, color=(0.78, 0.82, 0.88), width=0.6)
        y += ih + GAP

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_pdf))
    print(f"[make_ops_pdf] {out_pdf}  共 {doc.page_count} 页")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--section", action="append", default=[],
                    help='格式 "标题::说明::图片路径"，可重复')
    a = ap.parse_args()
    secs = []
    for s in a.section:
        parts = s.split("::")
        if len(parts) == 2:
            parts.append("")
        title, caption, img = parts[0], parts[1], parts[2]
        secs.append((title, caption, img))
    build(secs, Path(a.out))


if __name__ == "__main__":
    main()
