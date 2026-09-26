#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_shot.py —— 把 WSL 终端的真实文本输出渲染成「终端截图」PNG。

设计要点
--------
1. 尺寸由内容精确反推（行数 × 行高 + 边框），因此不会出现大片空白或截断；
2. 宽度按「显示宽度」计算（CJK 记 2 列），避免中文/长 URL 折行毁掉版式；
3. 用 Chrome headless 渲染，deviceScaleFactor=2，文字在打印/放大时依然锐利；
4. 颜色贴合深色主题终端（与 IDE 主题一致）。

用法
----
python make_shot.py --text shot1_raw.txt --title "..." --out shot1.png
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

FONT_PX = 13.5
LINE_RATIO = 1.52
PAD_X = 18
PAD_TOP = 14
PAD_BOTTOM = 16
BAR_H = 36
MAX_COLS = 168          # 超过则允许横向滚动式裁切前先缩字号
MIN_COLS = 86

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def disp_width(s: str) -> int:
    """终端显示宽度：CJK / 全角记 2 列。"""
    w = 0
    for ch in s:
        o = ord(ch)
        if (0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF or
                0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF or
                0xFE30 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60 or
                0xFFE0 <= o <= 0xFFE6 or 0x1F300 <= o <= 0x1FAFF):
            w += 2
        elif o == 9:
            w += 4
        else:
            w += 1
    return w


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).exists():
            return c
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    sys.exit("[make_shot] 找不到 Chrome/Edge，无法渲染截图")


def clean_lines(text: str) -> list[str]:
    text = ANSI_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    out = []
    for ln in text.split("\n"):
        out.append(ln.rstrip())
    # 去掉首尾连续空行
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def truncate_long(lines: list[str], max_cols: int) -> list[str]:
    res = []
    for ln in lines:
        if disp_width(ln) <= max_cols:
            res.append(ln)
            continue
        acc, w = "", 0
        for ch in ln:
            cw = disp_width(ch)
            if w + cw > max_cols - 1:
                acc += "…"
                break
            acc += ch
            w += cw
        res.append(acc)
    return res


def build_html(lines: list[str], title: str, subtitle: str,
               cols: int, font_px: float, prompt_hl: bool) -> str:
    body_rows = []
    for ln in lines:
        cls = "ln"
        # 高亮命令行提示符行
        if prompt_hl and (ln.lstrip().startswith("$ ") or ln.lstrip().startswith("# ")
                          or ln.lstrip().startswith("root@") or ln.lstrip().startswith("l@")):
            cls = "ln cmd"
        elif ln.startswith("[") and ("INFO" in ln or "WARN" in ln or "ERROR" in ln):
            cls = "ln logline"
        body_rows.append(f'<div class="{cls}">{html.escape(ln) if ln else "&nbsp;"}</div>')

    body = "\n".join(body_rows)
    line_h = font_px * LINE_RATIO
    n = max(len(lines), 1)
    min_height = int(round(BAR_H + PAD_TOP + n * line_h + PAD_BOTTOM))
    width = int(round(PAD_X * 2 + cols * font_px * 0.6005))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: #ffffff; }}
  /* 关键：窗口高度自适应内容（height:auto），再由渲染后的自动裁剪确定最终尺寸，
     这样完全不必依赖对字体行高的估算，避免内容被裁掉。 */
  .win {{
    width: {width}px; height: auto;
    background: #0f1620; border-radius: 10px; overflow: hidden;
    box-shadow: 0 10px 26px rgba(15,22,32,.28);
    border: 1px solid #253044;
  }}
  .bar {{
    height: {BAR_H}px; background: #1b2434; border-bottom: 1px solid #26334a;
    display: flex; align-items: center; padding: 0 14px; gap: 8px;
    font-family: "Segoe UI","Microsoft YaHei",sans-serif;
  }}
  .dot {{ width: 11px; height: 11px; border-radius: 50%; }}
  .d1 {{ background: #ff5f57; }} .d2 {{ background: #febc2e; }} .d3 {{ background: #28c840; }}
  .ttl {{
    margin-left: 10px; color: #9fb0c9; font-size: 12.5px; font-weight: 600;
    letter-spacing: .2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .ttl b {{ color: #e6edf7; font-weight: 700; }}
  .sub2 {{ margin-left: auto; color: #64809f; font-size: 11.5px; font-family: Consolas,monospace;
           white-space: nowrap; }}
  /* 注意：white-space:pre 只能加在 .ln 上。若加在 .body 上，HTML 源码里 div 之间的
     换行符也会被当成换行渲染，使实际行高翻倍、内容被裁掉。 */
  .body {{
    padding: {PAD_TOP}px {PAD_X}px {PAD_BOTTOM}px;
    font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", "Microsoft YaHei", monospace;
    font-size: {font_px}px; line-height: {LINE_RATIO};
    color: #d5e2f0; white-space: normal; tab-size: 4;
  }}
  .ln {{ height: {line_h:.2f}px; white-space: pre; overflow: hidden; }}
  .cmd {{ color: #8ee08e; font-weight: 700; }}
  .logline {{ color: #9db4d0; }}
</style></head>
<body>
  <div class="win">
    <div class="bar">
      <span class="dot d1"></span><span class="dot d2"></span><span class="dot d3"></span>
      <span class="ttl">{html.escape(title)}</span>
      <span class="sub2">{html.escape(subtitle)}</span>
    </div>
    <div class="body">{body}</div>
  </div>
</body></html>"""


def _row_is_dark(pix, y, cols, thresh=120):
    """判断某一行是否属于深色终端窗口（在若干采样列上取最暗值）。"""
    n = pix.n
    s = pix.samples
    w = pix.width
    best = 999
    for xf in cols:
        x = min(w - 1, max(0, int(w * xf)))
        i = (y * w + x) * n
        r, g, b = s[i], s[i + 1], s[i + 2]
        v = (r + g + b) / 3.0
        if v < best:
            best = v
    return best < thresh


def autocrop_dark(png_path: str) -> tuple[int, int]:
    """把渲染结果裁剪到深色终端窗口的实际包围盒（去掉多余白边）。"""
    pix = pymupdf.Pixmap(png_path)
    h, w = pix.height, pix.width
    cols = (0.03, 0.25, 0.5, 0.75, 0.97)

    top = None
    for y in range(h):
        if _row_is_dark(pix, y, cols):
            top = y
            break
    if top is None:
        return w, h
    bottom = h - 1
    for y in range(h - 1, -1, -1):
        if _row_is_dark(pix, y, cols):
            bottom = y
            break

    # 左右边界同样按行取样确定
    def col_is_dark(x):
        best = 999
        for yf in (0.3, 0.5, 0.7):
            y = min(h - 1, max(0, int(h * yf)))
            i = (y * w + x) * pix.n
            s = pix.samples
            v = (s[i] + s[i + 1] + s[i + 2]) / 3.0
            if v < best:
                best = v
        return best < 120

    left = 0
    for x in range(w):
        if col_is_dark(x):
            left = x
            break
    right = w - 1
    for x in range(w - 1, -1, -1):
        if col_is_dark(x):
            right = x
            break

    top = max(0, top - 2); bottom = min(h - 1, bottom + 2)
    left = max(0, left - 2); right = min(w - 1, right + 2)

    if (right - left + 1) >= w - 4 and (bottom - top + 1) >= h - 4:
        return w, h

    doc = pymupdf.open()
    page = doc.new_page(width=w, height=h)
    page.insert_image(pymupdf.Rect(0, 0, w, h), filename=png_path)
    clip = pymupdf.Rect(left, top, right + 1, bottom + 1)
    pix2 = page.get_pixmap(clip=clip)
    pix2.save(png_path)
    return pix2.width, pix2.height


def shot(text: str, out_png: str, title: str = "WSL Terminal",
         subtitle: str = "", max_cols: int = MAX_COLS,
         font_px: float = FONT_PX, prompt_hl: bool = True) -> tuple[int, int]:
    lines = clean_lines(text)
    if not lines:
        lines = ["(无输出)"]
    lines = truncate_long(lines, max_cols)
    cols = max(MIN_COLS, max(disp_width(l) for l in lines))
    cols = min(cols, max_cols)

    html_doc = build_html(lines, title, subtitle, cols, font_px, prompt_hl)

    tmpdir = Path(tempfile.mkdtemp(prefix="shot_"))
    hp = tmpdir / "shot.html"
    hp.write_text(html_doc, encoding="utf-8")
    out = Path(out_png).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    line_h = font_px * LINE_RATIO
    est_h = int(round(BAR_H + PAD_TOP + len(lines) * line_h + PAD_BOTTOM))
    # 窗口给足余量（内容多高就多高，裁剪交给 autocrop），避免任何裁切风险
    win_h = int(est_h * 1.8) + 120
    w = int(round(PAD_X * 2 + cols * font_px * 0.6005)) + 2

    chrome = find_chrome()
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--hide-scrollbars", "--force-device-scale-factor=2",
           f"--window-size={w},{win_h}", f"--screenshot={out}",
           "--default-background-color=FFFFFFFF",
           hp.as_uri()]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not out.exists():
        # 回退到旧版 headless
        cmd[1] = "--headless"
        subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not out.exists():
        sys.exit(f"[make_shot] 渲染失败\n{r.stdout}\n{r.stderr}")

    # 按深色窗口实际包围盒裁剪，得到精确尺寸
    fw, fh = autocrop_dark(str(out))
    return fw // 2, fh // 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True, help="输入文本文件，或 - 表示 stdin")
    ap.add_argument("--out", required=True, help="输出 PNG")
    ap.add_argument("--title", default="WSL Terminal")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--max-cols", type=int, default=MAX_COLS)
    ap.add_argument("--font-px", type=float, default=FONT_PX)
    ap.add_argument("--no-prompt-hl", action="store_true")
    a = ap.parse_args()

    if a.text == "-":
        text = sys.stdin.read()
    else:
        text = Path(a.text).read_text(encoding="utf-8", errors="replace")

    w, h = shot(text, a.out, a.title, a.subtitle, a.max_cols, a.font_px,
                not a.no_prompt_hl)
    print(f"[make_shot] {a.out}  ({w}x{h} css px @2x)")


if __name__ == "__main__":
    main()
