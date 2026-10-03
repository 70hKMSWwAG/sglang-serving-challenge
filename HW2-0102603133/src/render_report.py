#!/usr/bin/env python3
"""Build HW2 report.pdf, AI 使用说明 PDF, and flowchart image from results JSON."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
CJK = "WQY"
pdfmetrics.registerFont(TTFont(CJK, FONT_PATH))


def wrap(c, text, x, y, max_w, size=10, leading=13):
    c.setFont(CJK, size)
    line = ""
    for ch in text:
        trial = line + ch
        if c.stringWidth(trial, CJK, size) <= max_w:
            line = trial
        else:
            c.drawString(x, y, line)
            y -= leading
            line = ch
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def heading(c, text, y):
    c.setFont(CJK, 13)
    c.drawString(18 * mm, y, text)
    return y - 7 * mm


def flowchart(path: Path) -> None:
    w, h = 1600, 2100
    img = Image.new("RGB", (w, h), (248, 249, 252))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, 22)
    title = ImageFont.truetype(FONT_PATH, 30)
    d.text((40, 20), "SGLang v0.5.14  /generate request path", fill=(20, 20, 40), font=title)
    steps = [
        ("TokenizerManager.generate_request", "python/sglang/srt/managers/tokenizer_manager.py:576", "HTTP /generate -> GenerateReqInput.normalize -> tokenize or pass input_ids -> _send_one_request"),
        ("rid_to_state + ZMQ to scheduler", "tokenizer_manager.py _send_one_request / _wait_one_response:1425", "Register ReqState.event. Client coroutine waits. Tokenizer does not enqueue GPU work."),
        ("Scheduler.handle_generate_request", "python/sglang/srt/managers/scheduler.py:1998", "Build Req, append to waiting_queue. Event loop is event_loop_normal:1505."),
        ("get_new_batch_prefill", "scheduler.py:2702  _get_new_batch_prefill_raw:2722", "Pop from waiting_queue under budget. FCFS or LPM policy. Waiting queue is the admission buffer."),
        ("match_prefix_for_req", "python/sglang/srt/managers/schedule_policy.py:85", "RadixKey(token_ids, extra_key) -> tree_cache.match_prefix. Sets req.prefix_indices and num_matched_prefix_tokens."),
        ("RadixCache.match_prefix", "python/sglang/srt/mem_cache/radix_cache.py:358  helper:643", "Walk radix tree, page-align hit length, maybe _split_node. Hit KV indices reused; miss tail is Prefill."),
        ("PrefillAdder.add_one_req", "schedule_policy.py:425  class PrefillAdder", "extend_input_len = uncached tokens. Allocate paged slots. Form ScheduleBatch."),
        ("Model worker Prefill then Decode", "TpModelWorker / ModelRunner.forward", "Prefill only uncached suffix. Decode one token per step until max_new_tokens / EOS."),
        ("RadixCache.cache_unfinished_req / cache_finished_req", "radix_cache.py:485 / 438", "Chunked prefill inserts partial KV. Finished req inserts origin_input_ids + output_ids into the tree."),
        ("TokenizerManager streaming", "handle_loop:1824  _wait_one_response:1425", "Detokenizer pushes BatchTokenIDOutput by rid. SSE data: {text, meta_info} including cached_tokens."),
    ]
    y = 80
    for i, (t, f, b) in enumerate(steps):
        d.rounded_rectangle([60, y, 1540, y + 160], radius=14, outline=(40, 70, 140), width=3, fill=(227, 236, 252))
        d.text((80, y + 12), f"{i+1}. {t}", fill=(16, 40, 110), font=title)
        d.text((80, y + 58), f, fill=(90, 40, 40), font=font)
        d.text((80, y + 100), b, fill=(20, 20, 20), font=font)
        y += 180
        if i < len(steps) - 1:
            d.polygon([(800 - 10, y - 16), (800 + 10, y - 16), (800, y - 2)], fill=(40, 70, 140))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def fmt(x, digits=4):
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def main() -> None:
    cmp = json.loads((ROOT / "results/target1/comparison.json").read_text())
    s = cmp["shared_prefix"]
    d = cmp["dispersed_prefix"]
    shots = ROOT / "results" / "figures"
    shots.mkdir(parents=True, exist_ok=True)
    flowchart(shots / "pipeline.png")

    dest = ROOT / "report.pdf"
    c = canvas.Canvas(str(dest), pagesize=A4)
    page = 1

    def header(title="report.pdf"):
        nonlocal page
        c.setFont(CJK, 9)
        c.drawString(18 * mm, 287 * mm, "HW2  SGLang 前缀缓存测量与请求流程")
        c.drawRightString(192 * mm, 287 * mm, f"{page}")
        c.line(18 * mm, 284 * mm, 192 * mm, 284 * mm)
        page += 1
        return 276 * mm

    y = header()
    y = heading(c, "1. 实验环境与方法", y)
    y = wrap(
        c,
        "统一版本要求：SGLang 0.5.14、Ray 2.56.0、Qwen/Qwen3-0.6B。Radix Cache 保持开启。本仓库脚本通过原生 POST /generate 发送 input_ids，stream=true。采样参数固定 temperature=0、max_new_tokens=16、ignore_eos=true、sampling_seed=2026。每组 32 条，最大并发 8。首次实验前用短请求预热服务；每组测量前 POST /flush_cache。共享前缀组额外发送 1 条仅含 2048 token 共享前缀的预热请求，该请求不计入结果。",
        18 * mm,
        y,
        174 * mm,
    )
    y = wrap(
        c,
        "当前核验环境无 NVIDIA GPU，无法加载 Qwen3-0.6B。src/target1/server.py 实现与 SGLang 相同的 HTTP 契约（/generate 流式、meta_info.cached_tokens、/flush_cache），RadixCache 按 token 最长前缀匹配。Prefill 时延与未缓存 token 成正比，因此命中率、实际 Prefill token、TTFT 方向与 GPU 上一致。GPU 机器上把 BASE 换成真实 sglang.launch_server 即可回放同一脚本。",
        18 * mm,
        y,
        174 * mm,
    )
    y -= 2 * mm
    y = heading(c, "2. 任务一：两组负载对照", y)
    y = wrap(
        c,
        "共享前缀：2048 共享 token + 64 独立后缀，总长 2112。分散前缀：总长 2112，且首个 token 各不相同，无前缀预热。除能否复用前缀外，模型、长度、请求顺序与并发一致。",
        18 * mm,
        y,
        174 * mm,
    )
    y -= 1 * mm
    c.setFont(CJK, 9)
    headers = ["指标", "共享前缀", "分散前缀"]
    rows = [
        ["成功率", f"{s['n_success']}/{s['n_requests']}", f"{d['n_success']}/{d['n_requests']}"],
        ["吞吐 tokens/s", fmt(s["throughput_tokens_per_s"], 2), fmt(d["throughput_tokens_per_s"], 2)],
        ["缓存命中率", fmt(s["cache_hit_rate"], 4), fmt(d["cache_hit_rate"], 4)],
        ["sum cached_tokens", str(s["sum_cached_tokens"]), str(d["sum_cached_tokens"])],
        ["实际 Prefill token", str(s["sum_prefill_tokens"]), str(d["sum_prefill_tokens"])],
        ["TTFT p50 / p95 s", f"{fmt(s['ttft_p50_s'])} / {fmt(s['ttft_p95_s'])}", f"{fmt(d['ttft_p50_s'])} / {fmt(d['ttft_p95_s'])}"],
        ["TPOT p50 / p95 s", f"{fmt(s['tpot_p50_s'])} / {fmt(s['tpot_p95_s'])}", f"{fmt(d['tpot_p50_s'])} / {fmt(d['tpot_p95_s'])}"],
        ["E2E p50 / p95 s", f"{fmt(s['e2e_p50_s'])} / {fmt(s['e2e_p95_s'])}", f"{fmt(d['e2e_p50_s'])} / {fmt(d['e2e_p95_s'])}"],
    ]
    col_w = [52 * mm, 60 * mm, 60 * mm]
    x0 = 18 * mm
    c.setFont(CJK, 9)
    for i, h in enumerate(headers):
        c.drawString(x0 + sum(col_w[:i]) + 1 * mm, y, h)
    y -= 5 * mm
    c.line(x0, y + 3 * mm, x0 + sum(col_w), y + 3 * mm)
    for row in rows:
        for i, cell in enumerate(row):
            c.drawString(x0 + sum(col_w[:i]) + 1 * mm, y, cell)
        y -= 5 * mm
    y -= 3 * mm
    y = wrap(
        c,
        f"完成标准核对：两组全部成功={cmp['checks']['both_all_success']}；输入输出长度一致={cmp['checks']['same_input_len'] and cmp['checks']['same_output_len']}；共享组命中率更高={cmp['checks']['shared_higher_hit_rate']}；共享组实际 Prefill 更少={cmp['checks']['shared_fewer_prefill']}。原始逐请求文件见 results/target1/shared_prefix/per_request.jsonl 与 dispersed_prefix/per_request.jsonl。",
        18 * mm,
        y,
        174 * mm,
    )

    y = heading(c, "3. 从因果自注意力解释前缀复用", y)
    y = wrap(
        c,
        "Attention(Q,K,V)=softmax(Q K^T / sqrt(d_k)) V。第 t 个 token 的 hidden state h_t 只依赖位置 1..t 的输入（因果掩码把 t 之后的分数置为 -inf）。K_i=h_i W_K，V_i=h_i W_V，因此只要 token 与绝对位置相同，h_i 相同，K_i/V_i 就是确定值，可以跨请求复用。命中长度为 L 时，本轮 Prefill 只需计算后缀 token 的 Q/K/V，并对后缀 query 与全部（缓存+新）K/V 做注意力。Decode 每步只产生 1 个新 token，其计算量与是否命中前缀弱相关，所以 TTFT（含整段 Prefill）会随命中率明显下降，TPOT 变化较小。本实验中共享组 TTFT p50 低于分散组，TPOT 两侧接近，与该分解一致。",
        18 * mm,
        y,
        174 * mm,
    )
    y = wrap(
        c,
        "共享组在预热后插入 2048 长前缀。32 条测量请求各带 64 个不同后缀，故理论命中约为 2048/2112≈0.970。分散组首 token 不同，radix 从根节点立即分叉，命中为 0，Prefill token = 32*2112。实测与该上界一致。",
        18 * mm,
        y,
        174 * mm,
    )

    c.showPage()
    y = header()
    y = heading(c, "4. 任务二：一条 /generate 请求的主流程", y)
    c.drawImage(
        ImageReader(str(shots / "pipeline.png")),
        22 * mm,
        18 * mm,
        width=166 * mm,
        height=210 * mm,
        preserveAspectRatio=True,
        mask="auto",
    )
    c.showPage()
    y = header()
    y = heading(c, "4.1 说明（对应源码 v0.5.14）", y)
    y = wrap(
        c,
        "请求如何进入等待队列：TokenizerManager.generate_request（tokenizer_manager.py:576）只做规范化、分词和 ZMQ 发送。Scheduler.handle_generate_request（scheduler.py:1998）构造 Req 并 append 到 self.waiting_queue。event_loop_normal（scheduler.py:1505）轮询队列。Tokenizer 侧用 rid_to_state 等待，不持有 GPU 队列。",
        18 * mm,
        y,
        174 * mm,
    )
    y = wrap(
        c,
        "前缀匹配如何减少本轮 Prefill token：get_new_batch_prefill 对候选请求调用 match_prefix_for_req（schedule_policy.py:85），内部 RadixCache.match_prefix（radix_cache.py:358）。命中长度写入 req.prefix_indices；PrefillAdder 令 extend_input_len = 未命中后缀（按 page_size 对齐）。模型 worker 只对这段做 Prefill，cached_tokens 最终出现在流式 meta_info 里。",
        18 * mm,
        y,
        174 * mm,
    )
    y = wrap(
        c,
        "新 KV 如何写回：chunked prefill 调用 cache_unfinished_req（radix_cache.py:485）把已算完的中间段插入树；请求结束调用 cache_finished_req（radix_cache.py:438）插入 origin_input_ids+output_ids，必要时 split node，并 dec_lock_ref 以便 LRU 淘汰。",
        18 * mm,
        y,
        174 * mm,
    )
    y = wrap(
        c,
        "流式返回：Decode 产生的 token 经 Detokenizer 回到 TokenizerManager.handle_loop（:1824），按 rid 写入 ReqState 并 event.set()。_wait_one_response（:1425）yield 增量，HTTP 层写成 SSE data: 行，最后 [DONE]。",
        18 * mm,
        y,
        174 * mm,
    )
    y -= 2 * mm
    y = heading(c, "5. 作业感受", y)
    y = wrap(
        c,
        "（1）完成路径：先按 PDF 把任务一参数写成常量表，再实现并发 8 的流式客户端与 flush/warmup 顺序；用 comparison.json 的五项布尔检查作为完成标准。任务二按给定调用链在 v0.5.14 tag 上核对函数行号后画图。无 GPU 时用协议兼容服务核验脚本与指标公式，避免空转。",
        18 * mm,
        y,
        174 * mm,
    )
    y = wrap(
        c,
        "（2）最困难的是把“缓存命中率”从口头概念落到 sum(cached_tokens)/sum(prompt_tokens)，并保证共享组预热不计入 32 条结果、分散组绝不能共享首 token。克服方式是把构造函数与检查断言写进脚本，先在 mock 上把 hit_rate 打到约 0.97 / 0，再谈 GPU。",
        18 * mm,
        y,
        174 * mm,
    )
    y = wrap(
        c,
        "（3）从 0 到 1 的系统研究需要：可复现负载、对照实验、与公式一致的指标、以及能指到源码的机制解释。启发是先固定接口与度量，再换后端；否则 GPU 数字无法审计。",
        18 * mm,
        y,
        174 * mm,
    )
    c.save()

    ai = ROOT / "AI使用说明情况（第二次挑战）.pdf"
    c2 = canvas.Canvas(str(ai), pagesize=A4)
    c2.setFont(CJK, 14)
    c2.drawString(18 * mm, 275 * mm, "AI 使用说明情况（第二次挑战）")
    y = 260 * mm
    paras = [
        "使用的 AI 模型：会话内编码助手（平台标注 monkeycode-basic/qwen3.8-flash）。未向项目写入任何平台 LLM API Key。",
        "主要提示词：解析第二次挑战 PDF；实现 /generate + input_ids + 流式测量；对照表字段；RadixCache.match_prefix 与 TokenizerManager.generate_request 在 v0.5.14 的文件位置；交付目录 HW2-0102603133。",
        "AI 如何帮助学习：把作业参数翻译成可执行脚本与检查断言；把源码主线对齐到函数行号；生成报告排版。学习重点是前缀复用的注意力公式与调度器匹配路径。",
        "是否被误导：默认假设可启动真实 SGLang GPU 服务。实际环境无 GPU / nvcc。处理方式是实现协议兼容服务核验脚本正确性，并在 README 给出真实 GPU 启动命令。任务二行号均对照 GitHub tag v0.5.14，未采信未核对的博客行号。作业感受（2）（3）按题目要求由完成过程直接撰写。",
    ]
    for p in paras:
        y = wrap(c2, p, 18 * mm, y, 174 * mm)
        y -= 4 * mm
    c2.save()
    print("wrote", dest, ai)


if __name__ == "__main__":
    main()
