#!/usr/bin/env python3
"""生成 HW2 任务二的源码级请求流程图（SVG）与 HW1 的概念级 pipeline 图（SVG）。"""

from pathlib import Path

HW2_OUT = Path("/workspace/HW2/figures/request_flow.svg")
HW1_OUT = Path("/workspace/HW1/figures/pipeline.svg")

FONT = "Noto Sans CJK SC, DejaVu Sans, sans-serif"
MONO = "Noto Sans Mono CJK SC, DejaVu Sans Mono, monospace"

# 阶段配色
COLORS = {
    "io":     {"fill": "#e8f0fe", "stroke": "#4285f4", "text": "#0b3d91"},  # 接收/输出
    "queue":  {"fill": "#fff4e5", "stroke": "#f59e0b", "text": "#7c4a03"},  # 排队/调度
    "cache":  {"fill": "#e8f8ee", "stroke": "#12a150", "text": "#0b5132"},  # 缓存匹配
    "exec":   {"fill": "#f3e8fd", "stroke": "#8b5cf6", "text": "#4c1d95"},  # 模型执行
    "write":  {"fill": "#fde8e8", "stroke": "#dc2626", "text": "#7f1d1d"},  # 缓存写回
}


def node_svg(n, x, y, w, h):
    c = COLORS[n["kind"]]
    title, code = n["title"], n["code"]
    # 标题过长时缩小字号
    fs = 12 if len(title) <= 34 else 11
    return f"""<g>
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{c['fill']}" stroke="{c['stroke']}" stroke-width="1.4"/>
  <text x="{x + 10}" y="{y + 18}" font-family="{FONT}" font-size="{fs}" font-weight="700" fill="{c['text']}">{title}</text>
  <text x="{x + 10}" y="{y + 34}" font-family="{MONO}" font-size="9.5" fill="#444">{code}</text>
</g>"""


def arrow(x1, y1, x2, y2, dashed=False, label=""):
    dash = ' stroke-dasharray="5,4"' if dashed else ""
    mid_y = (y1 + y2) / 2
    lab = ""
    if label:
        lab = (f'<text x="{max(x1, x2) + 6}" y="{mid_y + 3}" font-family="{FONT}" '
               f'font-size="9.5" fill="#666">{label}</text>')
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#555" stroke-width="1.4" '
            f'marker-end="url(#ah)"{dash}/>{lab}')


def build_hw2():
    W, H = 1063, 770
    cols_x = [18, 548]
    col_w = 495
    node_h = 42
    gap = 50
    top = 82

    left = [
        ("① HTTP POST /generate", "srt/entrypoints/http_server.py:769  generate_request", "io"),
        ("② TokenizerManager.generate_request", "srt/managers/tokenizer_manager.py:576", "io"),
        ("③ _tokenize_one_request → input_ids", "tokenizer_manager.py:616（文本/ids → token ids）", "io"),
        ("④ _send_one_request → ZMQ IPC", "tokenizer_manager.py:620（→ Scheduler 进程）", "io"),
        ("⑤ Scheduler.event_loop_normal", "srt/managers/scheduler.py:1505", "queue"),
        ("⑥ recv_requests → process_input_requests", "scheduler.py:1512 / 1628", "queue"),
        ("⑦ _add_request_to_queue → waiting_queue", "scheduler.py:2258 / 2265  (请求进入等待队列)", "queue"),
        ("⑧ get_next_batch_to_run → get_new_batch_prefill", "scheduler.py:2702 / 2722", "queue"),
        ("⑨ policy.calc_priority（调度优先级）", "scheduler.py:2761  + PrefillAdder 构造 2778", "queue"),
    ]
    right = [
        ("⑩ req.init_next_round_input(tree_cache)", "scheduler.py:2847 → schedule_batch.py:1123", "cache"),
        ("⑪ RadixCache.match_prefix → prefix_indices", "srt/mem_cache/radix_cache.py:358（schedule_policy.py:85）", "cache"),
        ("⑫ extend_input_len = input_len − len(prefix)", "schedule_batch.py:1221 ⇦ 本轮真正要算的 token", "cache"),
        ("⑬ PrefillAdder.add_one_req（预算准入）", "srt/managers/schedule_policy.py:858 → can_run_list", "queue"),
        ("⑭ ScheduleBatch.init_new（组 batch）", "scheduler.py:2907", "exec"),
        ("⑮ run_batch → forward_batch_generation", "scheduler.py:3145 / tp_worker.py:65", "exec"),
        ("⑯ model_runner.forward → _forward_raw", "model_executor/model_runner.py:2896 / 2987", "exec"),
        ("⑰ Prefill（只算 extend 部分）+ Decode 迭代", "KV 写入 token_to_kv_pool；sampling 出新 token", "exec"),
        ("⑱ process_batch_result", "scheduler.py:3367 / batch_result_processor.py", "write"),
        ("⑲ 完成：release_kv_cache → cache_finished_req", "mem_cache/common.py:629 → radix_cache.py:438", "write"),
        ("⑳ 未完成：cache_unfinished_req（chunked/抢占）", "common.py:113 → radix_cache.py:485", "write"),
        ("㉑ IPC 回传：handle_loop → _handle_batch_output", "tokenizer_manager.py:1824 / 1839", "io"),
        ("㉒ state.out_list + event → _wait_one_response", "tokenizer_manager.py:1425 → SSE: data: {{...}}", "io"),
    ]

    nodes = []
    for i, (t, c, k) in enumerate(left):
        nodes.append(dict(id=f"L{i}", col=0, row=i, title=t, code=c, kind=k))
    for i, (t, c, k) in enumerate(right):
        nodes.append(dict(id=f"R{i}", col=1, row=i, title=t, code=c, kind=k))

    pos = {}
    for n in nodes:
        x = cols_x[n["col"]]
        y = top + n["row"] * gap
        pos[n["id"]] = (x, y)

    parts = []
    # 列标题（y=top-18，与上方主线说明保持间距）
    for i, name in enumerate(["请求接收 · 入队 · 调度",
                              "前缀匹配 · 执行 · 缓存写回 · 流式输出"]):
        parts.append(f'<text x="{cols_x[i]}" y="{top - 18}" font-family="{FONT}" '
                     f'font-size="12.5" font-weight="700" fill="#222">{name}</text>')

    edges = []
    for i in range(len(left) - 1):
        edges.append((f"L{i}", f"L{i+1}", "", False))
    for i in range(len(right) - 1):
        edges.append((f"R{i}", f"R{i+1}", "", False))
    # 跨列：左列末 → 右列首
    edges.append(("L8", "R0", "", False))
    # 回边：输出 → 客户端（右列末 → 左列首附近）
    edges.append(("R12", "L1", "流式回传", True))

    for a, b, lab, dash in edges:
        x1, y1 = pos[a]
        x2, y2 = pos[b]
        if a.startswith("L") and b.startswith("L"):
            p1 = (x1 + col_w / 2, y1 + node_h)
            p2 = (x2 + col_w / 2, y2)
        elif a.startswith("R") and b.startswith("R"):
            p1 = (x1 + col_w / 2, y1 + node_h)
            p2 = (x2 + col_w / 2, y2)
        elif a == "L8" and b == "R0":
            p1 = (x1 + col_w, y1 + node_h / 2)
            p2 = (x2, y2 + node_h / 2)
            parts.append(f'<path d="M {p1[0]} {p1[1]} L {p2[0] - 12} {p1[1]} L {p2[0] - 12} {p2[1]} '
                         f'L {p2[0]} {p2[1]}" fill="none" stroke="#555" stroke-width="1.4" '
                         f'marker-end="url(#ah)"/>')
            continue
        else:  # 回边 R12 → L1
            p1 = (x1, y1 + node_h / 2)
            p2 = (x2 + col_w, y2 + node_h / 2)
            parts.append(f'<path d="M {p1[0]} {p1[1]} L {p2[0] + 16} {p1[1]} L {p2[0] + 16} {p2[1]} '
                         f'L {p2[0]} {p2[1]}" fill="none" stroke="#888" stroke-width="1.3" '
                         f'stroke-dasharray="5,4" marker-end="url(#ah)"/>')
            parts.append(f'<text x="{p2[0] + 20}" y="{(p1[1] + p2[1]) / 2}" font-family="{FONT}" '
                         f'font-size="9.5" fill="#666">{lab}</text>')
            continue
        parts.append(arrow(p1[0], p1[1], p2[0], p2[1], dash))

    for n in nodes:
        x, y = pos[n["id"]]
        parts.append(node_svg(n, x, y, col_w, node_h))

    legend = []
    lx, ly = cols_x[0], H - 34
    for i, (k, name) in enumerate([("io", "接收/输出"), ("queue", "排队与调度"),
                                   ("cache", "前缀缓存匹配"), ("exec", "模型执行"),
                                   ("write", "缓存写回")]):
        c = COLORS[k]
        lx2 = lx + i * 195
        legend.append(f'<rect x="{lx2}" y="{ly - 10}" width="14" height="12" rx="2" fill="{c["fill"]}" '
                      f'stroke="{c["stroke"]}" stroke-width="1.2"/>'
                      f'<text x="{lx2 + 19}" y="{ly}" font-family="{FONT}" font-size="10.5" '
                      f'fill="#333">{name}</text>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <marker id="ah" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#555"/>
    </marker>
  </defs>
  <rect width="{W}" height="{H}" fill="#ffffff"/>
  <text x="18" y="28" font-family="{FONT}" font-size="15" font-weight="700" fill="#111">SGLang v0.5.14 · 一条 /generate 请求的主流程（源码级）</text>
  <text x="18" y="46" font-family="{FONT}" font-size="10.5" fill="#555">主线：TokenizerManager.generate_request → Scheduler.event_loop_normal / waiting_queue → get_new_batch_prefill / match_prefix → PrefillAdder / ScheduleBatch → model worker (Prefill, Decode) → RadixCache 写回 → 流式输出</text>
  {''.join(legend)}
  {''.join(parts)}
</svg>"""
    HW2_OUT.parent.mkdir(parents=True, exist_ok=True)
    HW2_OUT.write_text(svg, encoding="utf-8")
    print("wrote", HW2_OUT)


def build_hw1():
    """HW1 概念级流程图：client → tokenizer → scheduler/queue → prefill → KV Cache/RadixCache →
    decode → sampling → streaming output → metric"""
    W, H = 900, 560
    steps = [
        ("Client\n请求", "发送 prompt / input_ids", "io"),
        ("Tokenizer", "文本 → token ids", "io"),
        ("Scheduler\n/ Queue", "准入控制、组 batch、FCFS/LPM 调度", "queue"),
        ("Prefill", "input_ids → 计算 QKV，写 KV Cache\n命中前缀时只算未缓存部分", "exec"),
        ("KV Cache\n(RadixCache)", "page-sized 存储 + radix tree 前缀索引", "cache"),
        ("Decode\n(iterations)", "逐步生成，每步只读 KV Cache", "exec"),
        ("Sampling", "temperature/top_p/seed → 下一个 token", "exec"),
        ("Streaming\nOutput", "SSE 增量返回（stream_interval）", "io"),
        ("Metric", "TTFT / TPOT / E2E / 命中率 / 吞吐", "write"),
    ]
    # 布局：3 行 × 3 列 蛇形（order 元组为 (col, row)）
    bw, bh = 240, 92
    xs = [40, 330, 620]
    ys = [92, 250, 408]
    parts = []
    order = [(0, 0), (1, 0), (2, 0), (2, 1), (1, 1), (0, 1), (0, 2), (1, 2), (2, 2)]
    pos = {}
    for i, (c, r) in enumerate(order):
        pos[i] = (xs[c], ys[r])
    for i, (title, desc, kind) in enumerate(steps):
        x, y = pos[i]
        c = COLORS[kind]
        title_lines = title.split("\n")
        tsvg = "".join(
            f'<text x="{x + bw/2}" y="{y + 24 + k*16}" text-anchor="middle" font-family="{FONT}" '
            f'font-size="13" font-weight="700" fill="{c["text"]}">{t}</text>'
            for k, t in enumerate(title_lines))
        desc_lines = desc.split("\n")
        dsvg = "".join(
            f'<text x="{x + bw/2}" y="{y + 48 + len(title_lines)*16 + k*13}" text-anchor="middle" '
            f'font-family="{FONT}" font-size="9.5" fill="#555">{d}</text>'
            for k, d in enumerate(desc_lines))
        parts.append(f'<g><rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="8" fill="{c["fill"]}" '
                     f'stroke="{c["stroke"]}" stroke-width="1.5"/>{tsvg}{dsvg}</g>')

    # 连线（蛇形顺序 + 旁路：RadixCache 回指 Prefill/Decode）
    def center(i, side):
        x, y = pos[i]
        return {
            "b": (x + bw / 2, y + bh),
            "t": (x + bw / 2, y),
            "l": (x, y + bh / 2),
            "r": (x + bw, y + bh / 2),
        }[side]

    seq = [(0, "r", 1, "l"), (1, "r", 2, "l"), (2, "b", 3, "t"),
           (3, "l", 4, "r"), (4, "l", 5, "r"), (5, "b", 6, "t"),
           (6, "r", 7, "l"), (7, "r", 8, "l")]
    for a, sa, b, sb in seq:
        x1, y1 = center(a, sa)
        x2, y2 = center(b, sb)
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#555" stroke-width="1.5" '
                     f'marker-end="url(#ah2)"/>')
    # 缓存旁路：RadixCache(4) → Decode(5) 供给 KV
    x1, y1 = center(4, "b")
    x2, y2 = center(5, "l")
    parts.append(f'<path d="M {x1} {y1} L {x1} {y1 + 26} L {x2 - 14} {y1 + 26} L {x2 - 14} {y2} '
                 f'L {x2} {y2}" fill="none" stroke="#12a150" stroke-width="1.4" '
                 f'stroke-dasharray="5,4" marker-end="url(#ah2)"/>')
    parts.append(f'<text x="{x1 + 8}" y="{y1 + 22}" font-family="{FONT}" font-size="9.5" '
                 f'fill="#0b5132">命中前缀 → 复用 K/V，跳过重算</text>')

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <marker id="ah2" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">
      <path d="M0,0 L0,6 L8,3 z" fill="#555"/>
    </marker>
  </defs>
  <rect width="{W}" height="{H}" fill="#ffffff"/>
  <text x="40" y="34" font-family="{FONT}" font-size="16" font-weight="700" fill="#111">一次请求在 SGLang 在线推理框架中的完整流程</text>
  <text x="40" y="54" font-family="{FONT}" font-size="10.5" fill="#555">client → tokenizer → scheduler / queue → prefill → KV Cache / RadixCache → decode iterations → sampling → streaming output → metric</text>
  <text x="40" y="74" font-family="{FONT}" font-size="10.5" fill="#555">（HW1 挑战内容 3）</text>
  {''.join(parts)}
</svg>"""
    HW1_OUT.parent.mkdir(parents=True, exist_ok=True)
    HW1_OUT.write_text(svg, encoding="utf-8")
    print("wrote", HW1_OUT)


if __name__ == "__main__":
    build_hw2()
    build_hw1()
