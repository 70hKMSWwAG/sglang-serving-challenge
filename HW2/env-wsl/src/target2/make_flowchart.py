#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_flowchart.py —— 生成任务二要求的「一条 /generate 请求在 SGLang v0.5.14 中的完整流程」图

图中每个节点的函数名与「文件:行号」均在 python/sglang/srt 源码中逐一核对过
（源码版本 sglang 0.5.14，见本仓库 src/env/01_setup_env.sh 拉取的 SGL_VER）。

用法：
    python make_flowchart.py [输出目录]
默认输出 flowchart.svg 到脚本同目录。
"""

import os
import sys
import html

BAND_W = 764
BOX_X = 24
BOX_W = BAND_W - 12            # 左右各留 6px
BOX_H = 30
BOX_GAP = 8
BAND_HEADER = 20
BAND_PAD_TOP = 6
BAND_PAD_BOTTOM = 8
BAND_GAP = 11
MARGIN_X = 8
MARGIN_TOP = 52
MARGIN_BOTTOM = 10

TITLE_FS = 12.6
SUB_FS = 10.2

# 每个节点 = (标题, 位置说明, 是否高亮)
# ★ 高亮 = 任务书四个必答问题直接落在这几个节点上
BANDS = [
    ("① 接入层 · FastAPI HTTP（SSE 流式）", [
        ("generate_request —— POST /generate 路由",
         "entrypoints/http_server.py:765（路由）, 769（处理函数）", False),
        ("stream_results() 逐片产出 SSE",
         "entrypoints/http_server.py:773 → yield b\"data: \" + dumps_json(out) + b\"\\n\\n\"（:778）", False),
    ]),
    ("② TokenizerManager：请求规范化与下发", [
        ("TokenizerManager.generate_request",
         "managers/tokenizer_manager.py:576（normalize_batch_and_arguments → _init_req_state）", False),
        ("_tokenize_one_request → _send_one_request",
         "managers/tokenizer_manager.py:782, 1319（经 ZMQ 发往 Scheduler 进程）", False),
    ]),
    ("③ Scheduler 事件循环 → 等待队列", [
        ("event_loop_normal：recv_requests → process_input_requests",
         "managers/scheduler.py:1505（主循环）, 1628（请求入队分发）", False),
        ("_add_request_to_queue → self.waiting_queue.append(req)",
         "managers/scheduler.py:2258, 2265", True),
        ("get_next_batch_to_run → get_new_batch_prefill",
         "managers/scheduler.py:2702（组批入口）", False),
    ]),
    ("④ 前缀匹配与组批（PrefillAdder / ScheduleBatch）", [
        ("policy.calc_priority(waiting_queue, running_batch)",
         "managers/scheduler.py:2761（默认 cache_aware=LPM：最长前缀优先）", False),
        ("PrefillAdder（本轮 token 预算 / 准入控制）",
         "managers/schedule_policy.py:425（类定义）", False),
        ("Req.init_next_round_input → tree_cache.match_prefix",
         "managers/schedule_batch.py:1123, 1168（真正发起前缀匹配）", False),
        ("RadixCache.match_prefix → _match_prefix_helper",
         "mem_cache/radix_cache.py:358, 643（沿基数树逐段比对；命中止于节点中部时 _split_node:669）", False),
        ("set_extend_input_len( len(input) − len(prefix_indices) )",
         "managers/schedule_batch.py:1221 → 1525", True),
        ("PrefillAdder.add_one_req 通过 → 组装 ScheduleBatch",
         "managers/schedule_policy.py:858；managers/schedule_batch.py:1671", False),
    ]),
    ("⑤ Model Worker：Prefill 与 Decode", [
        ("Scheduler.run_batch → TpModelWorker.forward_batch_generation",
         "managers/scheduler.py:3145；managers/tp_worker.py:482", False),
        ("ModelRunner.forward（Prefill = extend / Decode = 自回归逐 token）",
         "model_executor/model_runner.py:2896；注意力后端 layers/attention/torch_native_backend.py:279 / 338", False),
        ("自回归循环：每步 Decode 产出 1 个 token，直到 finish_reason 非空",
         "本机 attention_backend='torch_native'（无 AMX 时自动回退，见服务端启动日志）", False),
    ]),
    ("⑥ 新产生的 KV 写回 RadixCache", [
        ("process_batch_result → batch_result_processor",
         "managers/scheduler.py:3367；managers/scheduler_components/batch_result_processor.py", False),
        ("maybe_cache_unfinished_req → RadixCache.cache_unfinished_req",
         "mem_cache/common.py:113；mem_cache/radix_cache.py:485（chunked prefill / 未结束请求的中间 KV）", True),
        ("release_kv_cache → RadixCache.cache_finished_req → insert",
         "mem_cache/common.py:629；mem_cache/radix_cache.py:438, 418（按 page 对齐后挂到基数树）", True),
    ]),
    ("⑦ 生成结果流式返回（Decode 每一步都会走一次）", [
        ("Scheduler.stream_output（打包 BatchTokenIDOutput）",
         "managers/scheduler_components/output_streamer.py:91", False),
        ("DetokenizerManager.event_loop（增量反分词）",
         "managers/detokenizer_manager.py:159", False),
        ("TokenizerManager._handle_batch_output → _wait_one_response → yield",
         "managers/tokenizer_manager.py:1839（组装 meta_info）, 1425（逐片 await 后 yield）", True),
        ("http_server.stream_results 逐片下发 SSE → 客户端 readline() 收到 data:{...}",
         "entrypoints/http_server.py:778；客户端 TTFT 即「首个非空 text 分片到达」的时刻", False),
    ]),
]


def esc(s):
    return html.escape(s, quote=False)


def build_svg():
    # 先算高度
    y = MARGIN_TOP
    layout = []
    for band_title, nodes in BANDS:
        band_top = y
        y += BAND_PAD_TOP + BAND_HEADER
        node_ys = []
        for _ in nodes:
            node_ys.append(y)
            y += BOX_H + BOX_GAP
        y -= BOX_GAP
        y += BAND_PAD_BOTTOM
        layout.append((band_title, nodes, band_top, y, node_ys))
        y += BAND_GAP
    total_h = y - BAND_GAP + MARGIN_BOTTOM

    cx = MARGIN_X + BAND_W / 2.0
    out = []
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {MARGIN_X*2+BAND_W} {total_h:.0f}" '
        f'width="100%" font-family="Noto Sans CJK SC, Source Han Sans SC, Microsoft YaHei, sans-serif">'
    )
    out.append(
        '<defs>'
        '<marker id="ah" markerWidth="9" markerHeight="9" refX="4.5" refY="4.5" orient="auto">'
        '<path d="M0,0 L9,4.5 L0,9 z" fill="#5b7699"/></marker>'
        '<marker id="ah2" markerWidth="9" markerHeight="9" refX="4.5" refY="4.5" orient="auto">'
        '<path d="M0,0 L9,4.5 L0,9 z" fill="#c8901a"/></marker>'
        '</defs>'
    )
    out.append(f'<rect x="0" y="0" width="{MARGIN_X*2+BAND_W}" height="{total_h:.0f}" fill="#ffffff"/>')
    out.append(
        f'<text x="{cx}" y="22" text-anchor="middle" font-size="15" font-weight="700" fill="#16283d">'
        '一条 /generate 请求在 SGLang v0.5.14 中的处理流程</text>'
    )
    out.append(
        f'<text x="{cx}" y="39" text-anchor="middle" font-size="10.5" fill="#5b6b7c">'
        '主流程（任务书指定主线）；括号内为文件路径与行号，均可在 python/sglang/srt 下核对</text>'
    )

    prev_bottom = None
    for band_title, nodes, band_top, band_bottom, node_ys in layout:
        out.append(
            f'<rect x="{MARGIN_X}" y="{band_top:.1f}" width="{BAND_W}" height="{band_bottom-band_top:.1f}" '
            f'rx="7" fill="#f6f9fc" stroke="#d3dfeb" stroke-width="1"/>'
        )
        out.append(
            f'<text x="{MARGIN_X+10}" y="{band_top+BAND_HEADER-3:.1f}" font-size="10.8" font-weight="700" '
            f'fill="#2b4a6f">{esc(band_title)}</text>'
        )
        for i, (nt, ns, hl) in enumerate(nodes):
            ny = node_ys[i]
            fill = "#fff9e8" if hl else "#ffffff"
            stroke = "#d9a72a" if hl else "#b9c9da"
            out.append(
                f'<rect x="{BOX_X}" y="{ny:.1f}" width="{BOX_W}" height="{BOX_H}" rx="5" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{1.4 if hl else 1}"/>'
            )
            marker = "★ " if hl else ""
            out.append(
                f'<text x="{BOX_X+10}" y="{ny+13.4:.1f}" font-size="{TITLE_FS}" font-weight="600" '
                f'fill="#16283d">{marker}{esc(nt)}</text>'
            )
            out.append(
                f'<text x="{BOX_X+10}" y="{ny+25.2:.1f}" font-size="{SUB_FS}" fill="#5b6b7c" '
                f'font-family="Consolas, Noto Sans CJK SC, Source Han Sans SC, Microsoft YaHei, sans-serif">{esc(ns)}</text>'
            )
            # 连线：上一个节点底部 → 本节点顶部
            if prev_bottom is not None:
                col = "#c8901a" if hl else "#5b7699"
                mk = "ah2" if hl else "ah"
                out.append(
                    f'<line x1="{cx}" y1="{prev_bottom:.1f}" x2="{cx}" y2="{ny-1:.1f}" '
                    f'stroke="{col}" stroke-width="1.3" marker-end="url(#{mk})"/>'
                )
            prev_bottom = ny + BOX_H
        # 跨 band 的连线在下一轮循环里用 prev_bottom 继续接
    out.append("</svg>")
    return "\n".join(out)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(outdir, exist_ok=True)
    svg = build_svg()
    path = os.path.join(outdir, "flowchart.svg")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(svg)
    n_nodes = sum(len(n) for _, n in BANDS)
    print(f"已写出 {path}（{len(svg)} 字节，{len(BANDS)} 个泳道，{n_nodes} 个节点）")


if __name__ == "__main__":
    main()
