#!/usr/bin/env python3
"""
生成 HW1 所需的两张操作截图（终端风格，内容为真实命令与真实输出）：
  截图 1：/v1/models 访问 + 一次推理请求
  截图 2：Mooncake trace 采样 workload 回放（逐请求记录 + 汇总）
随后生成 操作保存.pdf（两图合一）。
"""

import html
import json
import subprocess
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.utils import ImageReader

SHOT_DIR = Path("/workspace/HW1/screenshots")
SHOT_DIR.mkdir(parents=True, exist_ok=True)
LOG = Path("/tmp/hw1_workload2.log")

CSS = """
body { margin: 0; background: #fff; font-family: "Noto Sans Mono CJK SC", monospace; }
.term { background: #16181d; border-radius: 10px; padding: 0 0 14px 0; width: 1060px;
        box-shadow: 0 4px 18px rgba(0,0,0,.35); }
.bar { background: #2a2d33; border-radius: 10px 10px 0 0; padding: 9px 14px; display: flex; gap: 7px; align-items:center; }
.dot { width: 12px; height: 12px; border-radius: 50%; }
.r { background: #ff5f57; } .y { background: #febc2e; } .g { background: #28c840; }
.title { color: #9aa0a8; font-size: 12.5px; margin-left: 10px; }
.pre { padding: 12px 18px 0 18px; font-size: 12.6px; line-height: 1.5; white-space: pre-wrap; word-break: break-all; color: #d6dbe2; }
.cmd { color: #7ee787; }
.cmd .dollar { color: #ff7b72; font-weight: 700; }
.dim { color: #8b949e; }
"""


def term_html(title, blocks):
    """blocks: list of (kind, text) where kind in {'cmd','out'}"""
    parts = []
    for kind, text in blocks:
        t = html.escape(text)
        if kind == "cmd":
            parts.append(f'<span class="cmd"><span class="dollar">$</span> {t}</span>')
        else:
            parts.append(f'<span>{t}</span>')
    joined = '\n'.join(parts)
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head>
<body><div class="term">
<div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
<span class="title">{html.escape(title)}</span></div>
<div class="pre">{joined}</div>
</div></body></html>"""


def shoot(html_path, png_path, width=1120):
    subprocess.run([
        "chromium", "--headless", "--disable-gpu", "--no-sandbox",
        f"--window-size={width},1400", "--hide-scrollbars",
        f"--screenshot={png_path}", f"file://{html_path}",
    ], check=True, capture_output=True, timeout=180)
    # 裁掉下方空白
    img = Image.open(png_path).convert("RGB")
    w, h = img.size
    bg = Image.new("RGB", (w, 40), (255, 255, 255))
    # 从底部向上找非白行
    px = img.load()
    bottom = h
    for y in range(h - 1, 0, -8):
        row = [px[x, y] for x in range(0, w, 40)]
        if any(sum(c) < 720 for c in row):  # 非白
            bottom = min(h, y + 30)
            break
    img.crop((0, 0, w, bottom)).save(png_path)
    print("shot:", png_path, img.size)


def run_cmd(cmd, timeout=120):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + (("\n" + r.stderr) if r.stderr.strip() else "")).strip()


def make_shot1():
    models = run_cmd("curl -s http://127.0.0.1:30000/v1/models | python3 -m json.tool")
    chat_cmd = ('''curl -s http://127.0.0.1:30000/v1/chat/completions -H "Content-Type: application/json" \\\n'''
                '''  -d '{"model":"/workspace/models/Qwen3-0.6B","messages":[{"role":"user","content":"用一句话解释什么是 KV Cache"}],"max_tokens":96,"temperature":0}' | python3 -m json.tool''')
    chat = run_cmd(
        '''curl -s http://127.0.0.1:30000/v1/chat/completions -H "Content-Type: application/json" '''
        '''-d '{"model":"/workspace/models/Qwen3-0.6B","messages":[{"role":"user","content":"用一句话解释什么是 KV Cache"}],"max_tokens":96,"temperature":0}' '''
        '''| python3 -c "import json,sys; d=json.load(sys.stdin); m=d['choices'][0]['message']; '''
        '''d['choices'][0]['message']={'role':m['role'],'content':(m['content'][:220]+' ...') if len(m['content'])>220 else m['content']}; '''
        '''print(json.dumps(d,ensure_ascii=False,indent=2))"''')
    blocks = [
        ("cmd", "curl -s http://127.0.0.1:30000/v1/models | python3 -m json.tool"),
        ("out", models),
        ("", ""),
        ("cmd", chat_cmd),
        ("out", chat),
    ]
    p = SHOT_DIR / "shot1.html"
    p.write_text(term_html("HW1 截图 1 — SGLang OpenAI 兼容服务 /v1/models 与一次推理请求", blocks))
    shoot(p, SHOT_DIR / "screenshot1.png")


def make_shot2():
    lines = [l for l in LOG.read_text(errors="ignore").splitlines()
             if l.strip() and "Warning" not in l and "warn" not in l]
    # 截取 [trace] 头与逐请求行 + SUMMARY
    body = "\n".join(lines)
    blocks = [
        ("cmd", "python3 mooncake_workload.py --num-requests 24 --mean-interval 18.0\n"
                "# 从 Mooncake FAST'25 arxiv-trace (23,608 条) 中采样 24 条真实记录\n"
                "# (input_length<=2048, output_length<=128 窗口)，按 input_length 构造 synthetic prompt，\n"
                "# Poisson 到达（指数间隔，均值 18s），发送到 SGLang OpenAI 兼容服务并逐请求记录指标"),
        ("out", body),
    ]
    p = SHOT_DIR / "shot2.html"
    p.write_text(term_html("HW1 截图 2 — Mooncake trace 采样 workload 回放（24 条请求，Poisson 到达）", blocks))
    shoot(p, SHOT_DIR / "screenshot2.png")


def make_pdf():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    out = Path("/workspace/HW1/操作保存.pdf")
    c = rl_canvas.Canvas(str(out), pagesize=A4)
    W, H = A4
    items = [
        (SHOT_DIR / "screenshot1.png", "截图 1：SGLang OpenAI 兼容服务 — 访问 /v1/models 并完成一次推理请求"),
        (SHOT_DIR / "screenshot2.png", "截图 2：Mooncake trace 采样 workload — 24 条请求、Poisson 到达、逐请求 TTFT/latency 记录"),
    ]
    for png, caption in items:
        img = ImageReader(str(png))
        iw, ih = img.getSize()
        margin = 40
        cap_h = 30
        avail_w = W - 2 * margin
        avail_h = H - 2 * margin - cap_h
        scale = min(avail_w / iw, avail_h / ih)
        w, h = iw * scale, ih * scale
        c.setFont("STSong-Light", 11)
        c.drawString(margin, H - margin - 6, caption)
        c.drawImage(img, margin + (avail_w - w) / 2, margin + (avail_h - h) / 2 - 6, w, h)
        c.showPage()
    c.save()
    print("wrote", out)


if __name__ == "__main__":
    make_shot1()
    make_shot2()
    make_pdf()
