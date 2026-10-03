#!/usr/bin/env python3
"""Generate HW1/deliverables/操作保存.pdf from 环境① (WSL2 真机) screenshots.

Screenshots live in repo-root evidence/ (shot1 / shot2a / shot2b / shot3),
all captured on the real machine: Ubuntu 26.04, 12 vCPU, SGLang 0.5.14.

Usage:
    python HW1/src/make_shots_pdf.py
"""
import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def _find_cjk_font():
    for p in ('/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
              'C:/Windows/Fonts/msyh.ttc',
              'C:/Windows/Fonts/simhei.ttf'):
        if os.path.exists(p):
            return p
    raise RuntimeError('No CJK font found')


_FONT = _find_cjk_font()
pdfmetrics.registerFont(TTFont('CJK', _FONT, subfontIndex=0))
pdfmetrics.registerFont(TTFont('CJKB', _FONT, subfontIndex=0))

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))          # repo root
_EVIDENCE = os.path.join(_REPO, 'evidence')
_OUT = os.path.join(_REPO, 'HW1', 'deliverables', '操作保存.pdf')

W, H = A4
MARGIN = 40
TITLE = '操作保存（截图 1 / 2）'


def _wrap(text, font='CJK', size=8.6, maxw=W - 2 * MARGIN):
    """Greedy wrap that respects CJK (no spaces) and latin words."""
    out, cur = [], ''
    for ch in text:
        trial = cur + ch
        if pdfmetrics.stringWidth(trial, font, size) > maxw:
            out.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        out.append(cur)
    return out


FOOTER = ('运行环境：WSL2 · Ubuntu 26.04.1 LTS · Intel Core Ultra 5 338H (12 vCPU) · 15 GiB RAM · '
          'SGLang 0.5.14（源码编译，CPU/AVX2 基线）· Ray 2.56.0 · Qwen3-0.6B (bf16)。'
          '截图与终端文本均取自真实运行，原始记录见仓库 evidence/ 目录。')


def _page(c, badge, heading, caption_lines, img_path, footer=False):
    y = H - MARGIN - 18
    # title bar
    c.setFont('CJKB', 13)
    c.drawString(MARGIN, y, f'{TITLE}　—　{badge}')
    y -= 6
    c.setStrokeColorRGB(0.11, 0.30, 0.85)
    c.setLineWidth(1.6)
    c.line(MARGIN, y, W - MARGIN, y)
    y -= 18

    # heading
    c.setFont('CJKB', 10.5)
    c.drawString(MARGIN, y, heading)
    y -= 15

    # caption
    c.setFont('CJK', 8.6)
    c.setFillColorRGB(0.28, 0.33, 0.40)
    for ln in caption_lines:
        for sub in _wrap(ln):
            c.drawString(MARGIN, y, sub)
            y -= 12
    c.setFillColorRGB(0, 0, 0)
    y -= 8

    # image: fit into remaining box, keep aspect
    from reportlab.lib.utils import ImageReader
    iw, ih = ImageReader(img_path).getSize()
    box_w = W - 2 * MARGIN
    box_h = y - MARGIN - (22 if footer else 0)
    scale = min(box_w / iw, box_h / ih)
    dw, dh = iw * scale, ih * scale
    x = MARGIN + (box_w - dw) / 2
    c.drawImage(img_path, x, y - dh, width=dw, height=dh,
                mask='auto', anchor='c')
    c.setStrokeColorRGB(0.80, 0.84, 0.88)
    c.setLineWidth(0.6)
    c.rect(x, y - dh, dw, dh)
    if footer:
        c.setFont('CJK', 7.8)
        c.setFillColorRGB(0.40, 0.45, 0.52)
        fy = MARGIN - 4
        for ln in _wrap(FOOTER, size=7.8):
            c.drawString(MARGIN, fy, ln)
            fy -= 10
        c.setFillColorRGB(0, 0, 0)
    c.showPage()


def main():
    shots = [
        ('截图 1',
         '启动 SGLang 0.5.14 服务，并验证 GET /v1/models 与一次真实推理',
         ['在 WSL2（Ubuntu 26.04.1 LTS，12 vCPU / 15 GiB）以 OpenAI-compatible 方式启动 SGLang：',
          'python -m sglang.launch_server --model-path /opt/sgl-workspace/models/Qwen3-0.6B --device cpu --tp 1。',
          '日志显示：平台无 Intel AMX，自动回退 torch_native 后端；KV Cache 分配 81261 tokens（K/V 各 4.34 GB，bf16）；',
          'max_total_num_tokens=81261、chunked_prefill_size=2048、max_prefill_tokens=16384、context_len=40960；RadixCache 已初始化。',
          '随后 GET /v1/models 返回模型信息；POST /v1/chat/completions 完成一次真实推理（prompt 36 tokens，completion 250 tokens）。'],
         'shot1.png'),
        ('截图 2a',
         'Mooncake FAST\'25 trace 采样 + 泊松到达压测',
         ['从 mooncake_trace.jsonl（共 23608 条）随机采样 20 条（seed=2026），按每条记录的 input_length / output_length 构造',
          'synthetic prompt；相邻到达间隔服从指数分布，即严格的泊松到达过程（λ = 0.5 req/s，平均间隔 2.0 s）。',
          '逐条记录 input tokens / output tokens / status / TTFT / latency。'],
         'shot2a.png'),
        ('截图 2b',
         '逐请求结果汇总与统计',
         ['结果：成功率 20/20 = 100%，总墙钟 72.8 s，输出吞吐 12.28 tok/s；',
          'TTFT 均值 2113.5 ms（p50 1414.1 ms，p90 3952.1 ms）；端到端时延均值 25574.7 ms（p50 23812.2 ms，p90 44506.9 ms）。'],
         'shot2b.png'),
        ('附录',
         '服务端 RadixCache 前缀复用证据',
         ['服务端 Prefill batch 日志中 #cached-token > 0 即表示该请求的前缀已命中 RadixCache、对应 prefill 计算被跳过。',
          '本轮压测令所有请求共享 256 token 公共前缀（对应 Mooncake trace 中普遍共享的 hash_ids[0]）。',
          '全程 38 个 prefill 批次中有 29 个命中，占比 76.3%；命中长度以 256 与 1023/1024（整段 prompt 已缓存）为主。'],
         'shot3.png'),
    ]

    os.makedirs(os.path.dirname(_OUT), exist_ok=True)
    c = canvas.Canvas(_OUT, pagesize=A4)
    c.setTitle('操作保存')
    last = len(shots) - 1
    for i, (badge, heading, caps, img) in enumerate(shots):
        p = os.path.join(_EVIDENCE, img)
        if not os.path.exists(p):
            sys.exit('missing screenshot: ' + p)
        _page(c, badge, heading, caps, p, footer=(i == last))
    c.save()
    print('saved', _OUT)


if __name__ == '__main__':
    main()
