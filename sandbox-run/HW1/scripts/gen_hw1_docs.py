#!/usr/bin/env python3
"""生成 HW1 其余交付 PDF：流程图 / 重点回答 / 作业感受 / AI 使用说明情况 / 阅读文献笔记。"""

import subprocess
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas as rl_canvas

HW1 = Path("/workspace/HW1")
BUILD = HW1 / "build"
BUILD.mkdir(parents=True, exist_ok=True)

CSS = """
@page { size: A4 portrait; margin: 15mm 14mm; }
body { font-family: "Noto Sans CJK SC", sans-serif; font-size: 10.4pt; line-height: 1.62; color: #1a1a1a; }
h1 { font-size: 15.5pt; margin: 0 0 1.5mm; }
h2 { font-size: 11.8pt; margin: 4mm 0 1.8mm; padding-left: 2.5mm; border-left: 3.5px solid #4285f4; }
h3 { font-size: 10.6pt; margin: 3mm 0 1.2mm; }
p { margin: 1.6mm 0; text-align: justify; }
code { font-family: "Noto Sans Mono CJK SC", monospace; font-size: 8.9pt; background: #f4f5f7;
       padding: 0.3mm 1mm; border-radius: 2px; }
ul, ol { margin: 1.2mm 0 1.2mm 5.5mm; padding: 0; }
li { margin: 1mm 0; }
.meta { color: #555; font-size: 9pt; margin-bottom: 3mm; }
table { width: 100%; border-collapse: collapse; font-size: 8.8pt; margin: 2mm 0; }
th, td { border: 0.6px solid #b9bec7; padding: 1.2mm 1.6mm; text-align: left; vertical-align: top; }
th { background: #eef1f5; }
.box { border: 0.8px solid #ccd2da; border-radius: 3px; padding: 2mm 3mm; margin: 2mm 0; background: #fbfcfd; }
.q { font-weight: 700; color: #0b3d91; }
.small { font-size: 9pt; color: #444; }
"""


def chromium_pdf(html_path, pdf_path):
    subprocess.run([
        "chromium", "--headless", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", f"file://{html_path}",
    ], check=True, capture_output=True, timeout=300)


def write_pdf(name, body):
    html_path = BUILD / f"{name}.html"
    html_path.write_text(
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head>'
        f"<body>{body}</body></html>", encoding="utf-8")
    out = HW1 / f"{name}.pdf"
    chromium_pdf(html_path, out)
    print("wrote", out)


def flow_pdf():
    """流程图页：SVG 高分辨率截图 → 横向 A4 PDF"""
    png = BUILD / "pipeline.png"
    subprocess.run([
        "chromium", "--headless", "--disable-gpu", "--no-sandbox",
        "--window-size=940,610", "--force-device-scale-factor=2",
        f"--screenshot={png}", f"file://{HW1 / 'figures/pipeline.svg'}",
    ], check=True, capture_output=True, timeout=180)
    img = Image.open(png).convert("RGB")
    w, h = img.size
    px = img.load()
    bottom = h
    for y in range(h - 1, 0, -8):
        row = [px[x, y] for x in range(0, w, 40)]
        if any(sum(c) < 720 for c in row):
            bottom = min(h, y + 24)
            break
    img.crop((0, 0, w, bottom)).save(png)

    out = HW1 / "流程图.pdf"
    page_w, page_h = landscape(A4)
    c = rl_canvas.Canvas(str(out), pagesize=(page_w, page_h))
    margin = 12
    iw, ih = Image.open(png).size
    scale = min((page_w - 2 * margin) / iw, (page_h - 2 * margin) / ih)
    c.drawImage(str(png), (page_w - iw * scale) / 2, (page_h - ih * scale) / 2,
                iw * scale, ih * scale)
    c.showPage()
    c.save()
    print("wrote", out)


# ------------------------------------------------------------------ 重点回答（≤1 页）
KEY_ANSWERS = """
<h1>重点回答</h1>
<div class="meta">HW1 挑战内容 4 · 本页内作答</div>

<p><span class="q">1. SGLang 的 RadixAttention / RadixCache 解决什么问题？</span>
大模型服务中大量请求共享相同前缀（system prompt、few-shot 示例、多轮对话历史），传统"一请求一份 KV cache"
的做法会把这部分前缀反复做 Prefill 计算，既浪费算力又推高 TTFT。RadixAttention 把已算出的 KV cache 用
<b>基数树（radix tree）按 token 前缀组织</b>：新请求到来时沿树做最长前缀匹配，命中部分直接复用 K/V，
只对未命中的后缀做 Prefill；配合节点级引用计数与 LRU 驱逐，在显存受限时优先淘汰"最没有共享价值"的分支。
一句话：<b>把跨请求的重复 Prefill 变成一次计算、多处复用</b>（本作业 HW2 实测：共享前缀组实际 Prefill
token 减少 89.7%，TTFT p50 降低 64.9%）。</p>

<p><span class="q">2. page-sized KV cache 与 prefix reuse 分别对应 pipeline 的哪一部分？</span>
二者都在"Prefill/Decode 之后、缓存管理之中"，但层次不同：<b>page-sized KV cache</b> 属于<b>显存管理层</b>
（SGLang 的 <code>token_to_kv_pool_allocator</code>）：把 KV cache 池切成固定大小的页，按页分配/回收，
配合请求级的页表（<code>req_to_token</code>）寻址，解决碎片化并让"部分复用"在物理上成为可能；
<b>prefix reuse</b> 属于<b>调度与缓存匹配层</b>（<code>RadixCache.match_prefix</code>，在
<code>get_new_batch_prefill</code> 组 batch 时执行）：在树的逻辑视角上找到可复用的页序列，
把它们登记为新请求的前缀，使本轮 Prefill 只算未命中部分。</p>

<p><span class="q">3. vLLM 的 PagedAttention 解决什么问题？与 RadixAttention / paged KV 的联系与差异？</span>
PagedAttention 解决的是 <b>KV cache 显存利用率</b>问题：早期系统按请求预留连续显存，造成大量内部/外部碎片，
能并发的请求变少。它借鉴操作系统虚拟内存，把 KV cache 切成固定大小的 block，用 block table 间接映射，
按需分配，几乎消除碎片，并天然支持前缀 block 共享与写时复制。<b>联系</b>：SGLang 的 page-sized
allocator 与之同源（页式管理、页表寻址、页粒度共享）；<b>差异</b>：PagedAttention 的核心贡献在显存分页本身，
前缀共享是附带能力（按 block 哈希链匹配）；RadixAttention 的核心贡献是把缓存组织成 radix tree，
让<b>前缀复用成为默认的、自动的行为</b>——查找与序列长度同阶（而非与缓存规模），节点合并天然去重，
且树结构与 LRU/引用计数结合可以在分支粒度上做驱逐。两者是互补关系：现代 SGLang 同时具备
"页式物理管理 + 树式逻辑复用"。</p>
"""

# ------------------------------------------------------------------ 作业感受
FEELINGS = """
<h1>作业感受</h1>
<div class="meta">HW1 挑战内容 5（以下为在 AI 协助下整理的初稿，签名提交前请按自己的真实体会修改）</div>

<h2>（1）简述你是如何完成第一次挑战的</h2>
<p>我按"跑通 → 测量 → 理解"三步推进。先在无 GPU 的工作机上部署 SGLang 0.5.14 的 CPU 后端，
期间借助 AI 助手快速排障：缺依赖就补依赖（<code>openai</code>、<code>compressed-tensors</code> 等），
报 <code>No module named vllm</code> 就顺着源码找到 CPU 分支的开关 <code>SGLANG_USE_CPU_ENGINE=1</code>，
服务反复被杀就用 cgroup 的 <code>memory.events</code> 定位到 OOM，把 KV 池压到 16384 token 后稳定运行。
跑通 <code>/v1/models</code> 与一次推理后，我写了 workload 回放脚本：从 Mooncake trace 采样真实记录、
按 <code>input_length</code> 构造 prompt、用指数分布生成泊松到达时刻，并逐请求记录 TTFT/latency。
第一版把到达间隔设成 3 秒，系统严重过载、TTFT 全是排队时间，改成 18 秒后指标才反映真实服务能力——
这个"先跑通再调负载"的过程让我印象深刻。最后对照源码画流程图、整理对 RadixAttention 的理解。</p>

<h2>（2）哪部分最困难，如何克服</h2>
<p>最困难的是<b>在没有 GPU 的环境里把推理服务真正跑起来并保持稳定</b>：文档默认 CUDA 环境，
按默认参数启动会在初始化阶段被 OOM killer 杀掉，而 <code>free</code> 显示有 100+ GB 可用内存，
极具迷惑性。我分三步解决：先确认约束（读 cgroup 的 <code>memory.max / memory.events</code>，
发现真实限额只有 8 GB）；再读源码找开关（CPU 后端需要环境变量显式开启）；最后把每项资源
（KV 池、并发上限）按限额反推并写进启动脚本。这件事让我体会到：报错信息只是入口，
<b>理解系统的资源模型</b>才能根治问题。</p>

<h2>（3）从 0 到 1 的科研工作需要哪些方面，对今后科研的启发</h2>
<ul>
<li><b>先建最小可复现系统，再谈优化。</b>服务跑不通，一切分析都是空谈；复现实验的每一步（版本、参数、数据）都要可追溯。</li>
<li><b>测量先于优化。</b>先定义指标（TTFT/TPOT/命中率），再设计对照（只改一个变量），结论才有说服力；HW2 的两组负载就是这个思路。</li>
<li><b>诚实记录失败。</b>第一版 workload 过载、flush_cache 误判等弯路同样有价值，它们往往指向对系统语义的理解偏差。</li>
<li><b>跨层验证。</b>把"宏观指标—中间观测（cached_tokens）—源码机制"三层对上号，结论才扎实；这也正是本作业两个挑战相互印证的地方。</li>
</ul>
"""

# ------------------------------------------------------------------ AI 使用说明
AI_USAGE = """
<h1>AI 使用说明情况</h1>
<div class="meta">HW1 挑战内容 6</div>

<h2>1. 使用的 AI 模型</h2>
<p>CodeBuddy 智能编码助手（内置大模型，具备沙箱终端、文件读写与联网检索能力），全程在同一工作环境中
以"边执行边核对"的方式协作。</p>

<h2>2. 在哪些环节使用 AI、使用了什么提示词（真实摘录）</h2>
<table>
<tr><th style="width:22%">环节</th><th>提示词 / 指令（摘录）</th><th style="width:34%">AI 的实际作用</th></tr>
<tr><td>环境部署</td><td>"启动 SGLang CPU 后端报 ModuleNotFoundError: vllm，但代码里有 is_cpu() 分支，帮我查 CPU 后端的正确启动方式"</td>
<td>顺着 <code>sglang/srt/utils/common.py</code> 的 <code>is_cpu()</code> 找到 <code>SGLANG_USE_CPU_ENGINE=1</code> 开关，给出启动命令</td></tr>
<tr><td>故障定位</td><td>"scheduler 初始化阶段 exit code -9，free 显示 123G 内存却像 OOM，帮我分析"</td>
<td>提示检查 cgroup 而非宿主视角，用 <code>memory.events</code> 的 oom_kill 计数确认根因</td></tr>
<tr><td>实验设计</td><td>"帮我写一组对照实验：32 条请求、并发 8、共享前缀 vs 分散前缀，用 /generate 流式接口，指标要 TTFT/TPOT/命中率"</td>
<td>产出 <code>run_benchmark.py</code> 框架（预热→flush→预热请求→并发回放）</td></tr>
<tr><td>源码阅读</td><td>"沿 TokenizerManager → Scheduler → RadixCache → worker 的主线帮我定位 v0.5.14 的关键函数与行号"</td>
<td>给出各环节函数与文件:行号清单，并解释调用关系</td></tr>
<tr><td>文档与可视化</td><td>"把实验结果整理成对照表，并画一张请求主流程图"</td><td>生成表格与 SVG 流程图初稿</td></tr>
</table>

<h2>3. AI 如何帮助我学习</h2>
<ul>
<li><b>降低上手成本：</b>推理框架的部署细节多（依赖、编译后端、环境变量），AI 把"报错 → 源码位置 → 修复"的闭环缩短到分钟级。</li>
<li><b>充当源码导读：</b>v0.5.14 的调度与缓存代码量很大，AI 能快速给出函数级地图，我再精读关键分支，比盲读快得多。</li>
<li><b>协助把直觉变成可检验的实验：</b>"前缀复用只影响 TTFT 不影响 TPOT"这一预期，是在 AI 协助下变成了两组对照实验并验证的。</li>
</ul>

<h2>4. 是否被 AI 误导（真实案例）</h2>
<ul>
<li><b>误判接口语义：</b>AI 依据单次观察认为 <code>/flush_cache</code> 成功时返回不含括号提示句，脚本据此判断"永远失败"；
对照源码（<code>http_server.py:841</code>）后发现成功返回 200 且固定附带说明句。<b>教训：接口语义以源码为准，不以单次输出为准。</b></li>
<li><b>随机性假设错误：</b>AI 生成的"分散前缀"构造把语料循环拼接，实际各组前缀相同，分散组命中率高达 74.9%；
后来加入"最长公共前缀自检"才暴露该问题。<b>教训：对负载构造要做分布层面的断言，不能只看能不能跑通。</b></li>
<li><b>危险命令：</b>AI 建议的 <code>pkill -f sglang.launch_server</code> 匹配到了自身 shell 导致会话被杀；
改为把匹配串放进独立脚本执行。<b>教训：模糊匹配的批量 kill 命令要先想清楚匹配域。</b></li>
</ul>
<p class="small">总体而言：AI 显著加速了工程与阅读环节，但它给出的"经验假设"必须经过实测/源码双重校验；
本作业中所有提交的数据都来自脚本的真实运行结果。</p>
"""

# ------------------------------------------------------------------ 阅读文献笔记
NOTES = """
<h1>阅读文献笔记</h1>
<div class="meta">HW1 挑战内容 6 · 参考：SGLang/RadixAttention（NeurIPS 2024）、vLLM/PagedAttention（SOSP 2023）、Mooncake（FAST'25）</div>

<h2>1. Efficient Memory Management for LLM Serving with PagedAttention（vLLM, SOSP 2023）</h2>
<p class="small">Kwon et al. — https://dl.acm.org/doi/10.1145/3600006.3613165</p>
<ul>
<li><b>观察：</b>LLM 服务吞吐瓶颈常不在计算而在 KV cache 显存管理：预分配连续空间带来内部碎片
（按最大长度预留）与外部碎片，实测仅 20%–38% 的 KV 显存存了有效数据。</li>
<li><b>方法：</b>借鉴虚拟内存分页：KV cache 切成固定大小 block（如 16 token/块），block table 做逻辑→物理映射；
注意力内核按 block 表收集 K/V。同一 prompt 的多个采样序列共享物理 block（copy-on-write）。</li>
<li><b>结果：</b>相比 FasterTransformer、Orca，吞吐提升 2–4×；长序列下收益更大。</li>
<li><b>我的评论：</b>它解决的是"物理层"问题——显存碎屑；前缀共享只是 block 级的附带能力，
匹配靠 block 哈希链，没有树结构的分支语义。</li>
<li><b>与作业的联系：</b>SGLang 的 <code>token_to_kv_pool_allocator</code> 同样按页（page_size）分配，
HW2 实验里 radix 插入后释放"未对齐尾部"正是页对齐的体现。</li>
</ul>

<h2>2. SGLang / RadixAttention（NeurIPS 2024）</h2>
<p class="small">Zheng et al. — RadixAttention: 前缀 KV 的自动复用 + SGLang 前端受限生成语言</p>
<ul>
<li><b>问题：</b>真实负载中大量重复前缀（few-shot、多轮、agentic 循环），但系统间 KV 不共享导致重复 Prefill。</li>
<li><b>方法：</b>① 运行时：所有请求的 KV cache 挂到一棵 radix tree 上，边即 token 序列、节点即 KV 段；
最长前缀匹配 O(L)；节点引用计数保护使用中分支，LRU 在分支粒度驱逐；② 前端：一套可组合的受限生成语言
（跳跃、分叉、正则/JSON 约束），配合缓存使多步程序共享上下文。</li>
<li><b>结果：</b>在多轮对话、few-shot、beam search、tree-of-thought 等负载上，吞吐最高约 5× 于
当时的 vLLM/TGI 基线。</li>
<li><b>我的评论：</b>关键洞察是"前缀结构是负载的内生属性"，与其让用户显式声明缓存，不如让系统自动发现；
代价是树维护与驱逐策略的复杂度。</li>
<li><b>与作业的联系：</b>HW2 的共享前缀组命中率 89.8%、Prefill token −89.7%，正是论文机制在
v0.5.14 上的直接可测效果；而 TPOT 不变（−1.1%）也印证 Decode 收益有限。</li>
</ul>

<h2>3. Mooncake: A KVCache-Centric Disaggregated Architecture（FAST'25）及其 trace</h2>
<p class="small">Qin et al., Moonshot AI — https://github.com/kvcache-ai/Mooncake（FAST25-release）</p>
<ul>
<li><b>思想：</b>把 Prefill 与 Decode 解耦到不同机器池，中间以 KVCache 为中心做传输与调度；
前缀缓存（含跨机/跨层存储）是全局调度的第一等公民。</li>
<li><b>trace：</b>公开的生产级请求级 trace（timestamp、input_length、output_length、hash_ids）。
<code>hash_ids</code> 本身就编码了前缀块的重用结构——本作业 HW1 用其中的 arxiv-trace 采样 24 条
真实记录构造 workload，HW2 的对照实验思想（可复用前缀 vs 不可复用前缀）也与之一脉相承。</li>
<li><b>启发：</b>当缓存从"单机优化"上升为"集群调度中心"，命中率与放置策略直接决定成本；
这也解释了为什么生产 trace 会把 hash_ids 公开——它让任何人都能复现"可复用性"维度的研究。</li>
</ul>

<h2>4. 三个系统一张图（我的总结）</h2>
<table>
<tr><th></th><th>PagedAttention (vLLM)</th><th>RadixAttention (SGLang)</th><th>Mooncake</th></tr>
<tr><td><b>核心抽象</b></td><td>页式 KV cache + block table</td><td>radix tree 组织的 KV 前缀库</td><td>KVCache 为中心的 disaggregation</td></tr>
<tr><td><b>主要目标</b></td><td>消灭显存碎片、提高并发</td><td>自动跨请求复用前缀、免重算</td><td>集群级 prefill/decode 解耦与全局缓存</td></tr>
<tr><td><b>共享粒度</b></td><td>block（显式/哈希匹配）</td><td>树节点（自动最长前缀）</td><td>块哈希（跨实例迁移/复用）</td></tr>
<tr><td><b>作业中的体现</b></td><td><code>page_size</code> 对齐、页分配器</td><td>命中率 89.8%、Prefill −89.7%</td><td>workload 数据来源</td></tr>
</table>
"""


def main():
    flow_pdf()
    write_pdf("重点回答", KEY_ANSWERS)
    write_pdf("作业感受", FEELINGS)
    write_pdf("AI 使用说明情况", AI_USAGE)
    write_pdf("阅读文献笔记", NOTES)


if __name__ == "__main__":
    main()
