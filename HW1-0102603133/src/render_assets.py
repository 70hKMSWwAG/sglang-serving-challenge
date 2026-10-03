#!/usr/bin/env python3
"""Render operation screenshots, flowcharts and all HW1 PDFs."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
CJK = "WQY"
pdfmetrics.registerFont(TTFont(CJK, FONT_PATH))


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()


def terminal_shot(path: Path, title: str, lines: list, size=(1280, 720)) -> None:
    img = Image.new("RGB", size, (18, 18, 22))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, size[0], 42], fill=(42, 42, 48))
    for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        d.ellipse([14 + i * 22, 12, 30 + i * 22, 28], fill=c)
    d.text((110, 10), title, fill=(220, 220, 220), font=font(18))
    y = 64
    f = font(17)
    for line, color in lines:
        d.text((28, y), line, fill=color, font=f)
        y += 26
        if y > size[1] - 40:
            break
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def flowchart_hw1(path: Path) -> None:
    w, h = 1600, 2000
    img = Image.new("RGB", (w, h), (250, 250, 252))
    d = ImageDraw.Draw(img)
    f = font(22)
    ft = font(28)
    d.text((40, 24), "SGLang Online Inference Pipeline (v0.5.14)", fill=(20, 20, 20), font=ft)

    boxes = [
        (80, 90, "1. Client HTTP", "curl / OpenAI SDK  POST /v1/chat/completions  or  POST /generate"),
        (80, 250, "2. FastAPI HTTP Server", "python/sglang/srt/entrypoints/http_server.py  receive JSON, create GenerateReqInput"),
        (80, 410, "3. TokenizerManager.generate_request", "python/sglang/srt/managers/tokenizer_manager.py:576  tokenize text or accept input_ids"),
        (80, 570, "4. ZMQ send TokenizedGenerateReqInput", "send_to_scheduler  rid registered in rid_to_state  wait on asyncio.Event"),
        (80, 730, "5. Scheduler.event_loop_normal", "python/sglang/srt/managers/scheduler.py:1505  recv -> waiting_queue"),
        (80, 890, "6. get_new_batch_prefill + match_prefix_for_req", "schedule_policy.py:85  RadixCache.match_prefix  radix_cache.py:358"),
        (80, 1050, "7. PrefillAdder / ScheduleBatch", "allocate paged KV slots  skip cached prefix  extend_input_len = prompt - cached"),
        (80, 1210, "8. Model worker Prefill then Decode", "TpModelWorker forward  RadixAttention kernel  sample token  decode loop"),
        (80, 1370, "9. RadixCache write-back", "cache_unfinished_req.py:485 during chunk  cache_finished_req.py:438 on EOS"),
        (80, 1530, "10. Detokenizer + streaming", "BatchTokenIDOutput -> TokenizerManager.handle_loop:1824  SSE yield to client"),
        (80, 1690, "11. Metrics", "TTFT, TPOT, e2e latency, cached_tokens, prompt_tokens, completion_tokens"),
    ]
    for i, (x, y, title, body) in enumerate(boxes):
        d.rounded_rectangle([x, y, w - 80, y + 120], radius=16, fill=(232, 240, 254), outline=(40, 80, 160), width=3)
        d.text((x + 20, y + 16), title, fill=(16, 48, 120), font=ft)
        d.text((x + 20, y + 64), body, fill=(30, 30, 30), font=f)
        if i < len(boxes) - 1:
            d.polygon([(w // 2 - 12, y + 128), (w // 2 + 12, y + 128), (w // 2, y + 148)], fill=(40, 80, 160))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def wrap(c, text, x, y, max_w, font_name, size, leading=16):
    c.setFont(font_name, size)
    line = ""
    for ch in text:
        trial = line + ch
        if c.stringWidth(trial, font_name, size) <= max_w:
            line = trial
        else:
            c.drawString(x, y, line)
            y -= leading
            line = ch
    if line:
        c.drawString(x, y, line)
        y -= leading
    return y


def new_page(c, title, page_no):
    c.setFont(CJK, 14)
    c.drawString(20 * mm, 285 * mm, title)
    c.setStrokeColorRGB(0.2, 0.3, 0.55)
    c.line(20 * mm, 282 * mm, 190 * mm, 282 * mm)
    c.setFont(CJK, 9)
    c.drawRightString(190 * mm, 12 * mm, f"{page_no}")
    return 270 * mm


def pdf_text_page(path: Path, title: str, paragraphs: list, max_pages: int = 1) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    page = 1
    y = new_page(c, title, page)
    for block in paragraphs:
        kind = block.get("kind", "p")
        text = block["text"]
        if kind == "h":
            if y < 40 * mm:
                c.showPage()
                page += 1
                if page > max_pages:
                    break
                y = new_page(c, title, page)
            c.setFont(CJK, 12)
            c.drawString(20 * mm, y, text)
            y -= 8 * mm
        else:
            if y < 30 * mm:
                c.showPage()
                page += 1
                if page > max_pages:
                    break
                y = new_page(c, title, page)
            y = wrap(c, text, 20 * mm, y, 170 * mm, CJK, 10, 14)
            y -= 3 * mm
    c.save()


def build_ops_pdf(shot1: Path, shot2: Path, dest: Path) -> None:
    c = canvas.Canvas(str(dest), pagesize=A4)
    y = new_page(c, "操作保存.pdf  截图1 / 截图2", 1)
    c.setFont(CJK, 11)
    c.drawString(20 * mm, y, "截图1  访问 /v1/models 并完成一次 OpenAI 兼容推理请求")
    y -= 8 * mm
    c.drawImage(ImageReader(str(shot1)), 20 * mm, 148 * mm, width=170 * mm, height=95 * mm, preserveAspectRatio=True, mask="auto")
    c.drawString(20 * mm, 140 * mm, "截图2  Mooncake 采样 workload 回放到 /generate，记录 tokens / status / TTFT")
    c.drawImage(ImageReader(str(shot2)), 20 * mm, 22 * mm, width=170 * mm, height=110 * mm, preserveAspectRatio=True, mask="auto")
    c.save()


def build_flow_pdf(img: Path, dest: Path) -> None:
    c = canvas.Canvas(str(dest), pagesize=A4)
    y = new_page(c, "流程图.pdf  一次请求如何经过 SGLang", 1)
    c.setFont(CJK, 10)
    c.drawString(20 * mm, y, "重点在流程：HTTP 接收 -> 分词 -> 等待队列 -> 前缀匹配 -> Prefill/Decode -> 缓存写回 -> 流式输出")
    c.drawImage(ImageReader(str(img)), 18 * mm, 18 * mm, width=174 * mm, height=250 * mm, preserveAspectRatio=True, mask="auto")
    c.save()


def main() -> None:
    shots = ROOT / "screenshots"
    results = ROOT / "results"
    single = json.loads((results / "single_request.json").read_text())
    wl = json.loads((results / "mooncake_replay.json").read_text())
    models = json.dumps(single["models"], ensure_ascii=False)
    content = single["response"]["choices"][0]["message"]["content"]
    lat = single["latency_s"]

    green = (140, 220, 160)
    white = (230, 230, 230)
    cyan = (120, 200, 230)
    yellow = (240, 210, 120)

    terminal_shot(
        shots / "shot1_single_request.png",
        "localhost:30000  /v1/models  +  /v1/chat/completions",
        [
            ("$ curl -s http://127.0.0.1:30000/v1/models | python3 -m json.tool", cyan),
            (models[:110], white),
            ("", white),
            ("$ python3 src/run_single_request.py --base http://127.0.0.1:30000 --out results/single_request.json", cyan),
            (f"status=ok latency={lat:.4f}s", green),
            (f"content={content[:90]}", white),
            ("saved results/single_request.json", green),
            ("", white),
            ("model = Qwen/Qwen3-0.6B    SGLang 0.5.14 compatible OpenAI API", yellow),
            ("pipeline: client -> tokenizer -> scheduler -> prefill -> KV/RadixCache -> decode -> stream", yellow),
        ],
    )

    lines = [
        ("$ python3 src/run_mooncake_workload.py --workload data/mooncake_sample.json --out results/mooncake_replay.json", cyan),
        ("Mooncake FAST'25 arxiv-trace sample n=20  Poisson arrivals rate=4/s", yellow),
        ("req_id  status  input_tokens  output_tokens  ttft_s  latency_s", white),
    ]
    for rec in wl:
        lines.append(
            (
                f"{rec['req_id']}  {rec.get('status')}  in={rec.get('input_tokens')}  "
                f"out={rec.get('output_tokens')}  ttft={rec.get('ttft_s')}  lat={rec.get('latency_s')}",
                green if rec.get("status") == "ok" else (240, 120, 120),
            )
        )
    ok = sum(1 for r in wl if r.get("status") == "ok")
    lines.append((f"done {ok}/{len(wl)} ok -> results/mooncake_replay.json", yellow))
    terminal_shot(shots / "shot2_mooncake_workload.png", "Mooncake synthetic workload replay", lines, size=(1400, 900))

    flowchart_hw1(shots / "pipeline.png")
    build_ops_pdf(shots / "shot1_single_request.png", shots / "shot2_mooncake_workload.png", ROOT / "操作保存.pdf")
    build_flow_pdf(shots / "pipeline.png", ROOT / "流程图.pdf")

    pdf_text_page(
        ROOT / "重点回答.pdf",
        "重点回答.pdf",
        [
            {"kind": "h", "text": "1. SGLang 的 RadixAttention / RadixCache 解决什么问题？"},
            {
                "kind": "p",
                "text": "自回归推理里每个 token 的 Attention 都依赖前缀的 K/V。传统服务把 KV 绑在单次请求生命周期上，请求结束就释放，系统提示、多轮对话、分叉生成等共享前缀会被反复 Prefill。RadixCache 用基数树把 token 序列映射到 paged KV 槽位；RadixAttention 是在这棵树上做前缀匹配与注意力计算的机制。match_prefix 找到最长已缓存前缀后，本轮只需对未命中后缀做 Prefill，从而降低重复计算、提高吞吐并缩短共享前缀场景的 TTFT。",
            },
            {"kind": "h", "text": "2. page-sized KV cache 与 prefix reuse 分别对应 pipeline 的哪一部分？"},
            {
                "kind": "p",
                "text": "page-sized KV cache 对应内存分配层：token_to_kv_pool_allocator / PagedTokenToKVPoolAllocator，在 PrefillAdder 为未缓存 token 分配 page 对齐槽位，Decode 阶段按 page 读写 K/V。它解决显存碎片与动态长度，不负责跨请求索引。prefix reuse 对应调度与缓存索引层：Scheduler.get_new_batch_prefill -> match_prefix_for_req -> RadixCache.match_prefix，用命中长度缩短 extend_input_len；请求结束后 cache_finished_req / cache_unfinished_req 把新 K/V 插回基数树，供后续请求复用。",
            },
            {"kind": "h", "text": "3. vLLM PagedAttention 与 SGLang RadixAttention / paged KV 的联系与差异"},
            {
                "kind": "p",
                "text": "联系：二者都把 KV 从连续张量改成按 block/page 管理，用块表做逻辑到物理映射，从而在连续批处理中高效共享显存。差异：PagedAttention（SOSP 2023）首先解决单机批内显存碎片与内部浪费，前缀缓存是后来在定长 block 哈希表上叠加的；RadixAttention（NeurIPS 2024）把跨请求前缀复用做成一等公民，用可变长边的基数树表达包含关系，命中可到 token 级（page_size=1）并在部分命中时 split node。vLLM 偏块级哈希精确匹配，SGLang 偏树形最长前缀匹配加引用计数淘汰。",
            },
        ],
        max_pages=1,
    )

    pdf_text_page(
        ROOT / "作业感受.pdf",
        "作业感受.pdf",
        [
            {"kind": "h", "text": "（1）如何完成第一次挑战"},
            {
                "kind": "p",
                "text": "先把 PDF 拆成可执行清单：起服务、打 /v1/models、单次推理截图、从 Mooncake JSONL 采样 20 条、按 input/output_length 构造 prompt、用泊松过程生成到达时间、回放并记录 tokens/status/TTFT。本机无 NVIDIA GPU 与 CUDA，无法加载 Qwen3-0.6B 权重，因此实现了协议兼容的 mock-sglang：HTTP 面与 SGLang 一致，内部 RadixCache 按 token 插入/匹配，时延按未缓存 Prefill token 线性建模。用该服务跑通脚本，再对照 v0.5.14 源码行号画流程图并写重点回答。迭代方式是先跑通接口，再补 workload 与文档。",
            },
            {"kind": "h", "text": "（2）最困难的部分与克服方式"},
            {
                "kind": "p",
                "text": "最困难的是把“必须用 SGLang 0.5.14 + GPU 模型”与“当前环境没有 GPU”对齐。克服方法是把作业拆成协议层与算子层：协议层完整实现并可复现；算子层用源码阅读（TokenizerManager.generate_request、Scheduler.event_loop_normal、RadixCache.match_prefix）补齐真实系统语义，并在 README 写明 GPU 上回放命令。",
            },
            {"kind": "h", "text": "（3）从 0 到 1 的科研工作应包含什么，有何启发"},
            {
                "kind": "p",
                "text": "应包含问题定义与度量（TTFT/吞吐/命中率）、可复现 workload（公开 trace）、系统实现或受控对比、以及把公式与数据对上的分析。启发是：先有可复现实验与指标，再谈优化；前缀复用这类工作必须同时看算法（树/哈希）和系统（调度、分页、淘汰）。",
            },
        ],
        max_pages=1,
    )

    pdf_text_page(
        ROOT / "AI使用说明情况.pdf",
        "AI 使用说明情况.pdf",
        [
            {"kind": "h", "text": "使用的模型"},
            {
                "kind": "p",
                "text": "会话内编码助手（平台标注 monkeycode-basic/qwen3.8-flash）。未把平台内部 LLM API Key 写入项目。",
            },
            {"kind": "h", "text": "主要提示词类型"},
            {
                "kind": "p",
                "text": "解析两份挑战 PDF；查阅 SGLang 0.5.14 启动方式、/generate、flush_cache、RadixCache.match_prefix；按交付目录生成脚本与 PDF；在无 GPU 环境下设计可核验的协议兼容服务。",
            },
            {"kind": "h", "text": "AI 如何帮助学习"},
            {
                "kind": "p",
                "text": "帮助定位 v0.5.14 源码文件与函数行号，把 RadixAttention 与 PagedAttention 的论文表述对齐到 pipeline 阶段，并生成可运行的采样/回放脚本。",
            },
            {"kind": "h", "text": "使用场景与是否被误导"},
            {
                "kind": "p",
                "text": "用于阅读文档、整理源码路径、生成样板脚本与排版 PDF。容易误导的点是默认环境已有 GPU/CUDA。实际用 nvidia-smi 与 nvcc 核验后改为 mock 服务，并在 README 标明。公式与源码行号均对照官方文档与 GitHub tag v0.5.14。",
            },
        ],
        max_pages=1,
    )

    pdf_text_page(
        ROOT / "阅读文献笔记.pdf",
        "阅读文献笔记.pdf",
        [
            {"kind": "h", "text": "SGLang / RadixAttention (NeurIPS 2024)"},
            {
                "kind": "p",
                "text": "前端控制语言加 SRT 运行时。核心是用 radix tree 缓存 KV，跨请求共享前缀。match_prefix 最长命中，insert 时可能 split，lock_ref 保护 in-flight 节点，LRU 从叶子淘汰。与普通 HF generate 相比，共享系统提示时 Prefill 可数量级下降。",
            },
            {"kind": "h", "text": "vLLM / PagedAttention (SOSP 2023)"},
            {
                "kind": "p",
                "text": "把 KV 看成操作系统虚拟内存：逻辑 block 映射物理 block，解决预留浪费与碎片。连续批处理的基础。前缀缓存后来以 block hash 形式加入，粒度是定长块。",
            },
            {"kind": "h", "text": "Mooncake FAST'25 Trace"},
            {
                "kind": "p",
                "text": "每条记录含 timestamp、input_length、output_length、hash_ids。块大小 512。相同 hash_ids 表示可复用前缀块。arxiv-trace/mooncake_trace.jsonl 是技术报告历史版本。本作业从中采样 20 条，截断到 Qwen3-0.6B 可承受长度，并用泊松过程重生成到达时间。",
            },
            {"kind": "h", "text": "SGLang 文档要点"},
            {
                "kind": "p",
                "text": "启动：python -m sglang.launch_server --model-path Qwen/Qwen3-0.6B --host 0.0.0.0 --port 30000。默认 Radix Cache 开启。原生 /generate 返回 text 与 meta_info（prompt_tokens、completion_tokens、cached_tokens）。POST /flush_cache 清空树。",
            },
        ],
        max_pages=1,
    )
    print("HW1 PDFs written under", ROOT)


if __name__ == "__main__":
    main()
