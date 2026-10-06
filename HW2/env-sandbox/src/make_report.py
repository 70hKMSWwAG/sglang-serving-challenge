#!/usr/bin/env python3
"""
生成 HW2 report.pdf（正文 ≤8 页）。

内容：
  任务一 前缀缓存测量（实验设计、对照主表、因果自注意力公式解释、TTFT/TPOT 差异分析）
  任务二 /generate 请求主流程源码阅读（流程图 + 关键函数/文件说明）

用法：python3 make_report.py
输出：/workspace/HW2/report.pdf
"""

import json
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("/workspace/HW2")
BUILD = ROOT / "build"
BUILD.mkdir(parents=True, exist_ok=True)
SUMMARY = json.loads((ROOT / "results/target1/summary.json").read_text())
MEAN = SUMMARY["mean"]
FLOW_SVG = (ROOT / "figures/request_flow.svg").read_text(encoding="utf-8")

FONT_CSS = '"Noto Sans CJK SC", "Noto Sans", sans-serif'
MONO_CSS = '"Noto Sans Mono CJK SC", monospace'

# ---------------------------------------------------------------- 公式图片
FORMULAS = {
    "attn": r"$\mathrm{Attention}(Q,K,V)=\mathrm{softmax}\!\left(\frac{QK^{\top}}{\sqrt{d_k}}\right)V$",
    "causal": r"$A=\mathrm{softmax}(QK^{\top}/\sqrt{d_k}+M)V,\quad M_{ij}=0\ (j \leq i),\ -\infty\ (j>i)$",
    "kv": r"$k_i=f(x_i,\mathrm{pos}(i)),\ v_i=g(x_i,\mathrm{pos}(i))\ \Rightarrow\ K_{1:m},V_{1:m}\ \mathrm{depend\ only\ on}\ x_{1:m}$",
    "prefill": r"$N_{\mathrm{prefill}}=n-m,\qquad \mathrm{per\ decode\ step}:\ \mathrm{reads}\ n\ \mathrm{K/V}\ (\mathrm{independent\ of}\ m)$",
}


def render_formulas():
    paths = {}
    for key, tex in FORMULAS.items():
        fig = plt.figure(figsize=(7.2, 0.55), dpi=200)
        fig.text(0.01, 0.42, tex, fontsize=15)
        p = BUILD / f"formula_{key}.png"
        fig.savefig(p, transparent=True, bbox_inches="tight", pad_inches=0.05)
        plt.close(fig)
        paths[key] = p
    return paths


# ---------------------------------------------------------------- 表格
def fmt(v, spec="{:.3f}"):
    return spec.format(v) if isinstance(v, (int, float)) else "-"


TABLE_ROWS = [
    ("成功率", "success_rate", "{:.1%}"),
    ("缓存命中率", "cache_hit_rate", "{:.2%}"),
    ("实际执行 Prefill 的 token 数（合计）", "total_actual_prefill_tokens", "{:,.0f}"),
    ("单请求平均实际 Prefill token", "avg_actual_prefill_tokens_per_request", "{:,.1f}"),
    ("吞吐量（输出 token/s）", "output_token_throughput_tps", "{:.3f}"),
    ("吞吐量（请求/s）", "request_throughput_rps", "{:.3f}"),
    ("TTFT p50 (s)", "ttft_p50_s", "{:.3f}"),
    ("TTFT p95 (s)", "ttft_p95_s", "{:.3f}"),
    ("TPOT p50 (s)", "tpot_p50_s", "{:.3f}"),
    ("TPOT p95 (s)", "tpot_p95_s", "{:.3f}"),
    ("端到端延迟 p50 (s)", "e2e_p50_s", "{:.3f}"),
    ("端到端延迟 p95 (s)", "e2e_p95_s", "{:.3f}"),
]


def main_table():
    rows = []
    for label, key, spec in TABLE_ROWS:
        a = MEAN[key]["shared_prefix"]
        b = MEAN[key]["dispersed_prefix"]
        if key == "success_rate":
            diff = "—"
        elif key == "cache_hit_rate":
            # 命中率是比率量，用「百分点」而不是相对百分比，避免出现 -15933% 这类无意义数字
            diff = f"{(a - b) * 100:+.2f} pp"
        elif key in ("total_actual_prefill_tokens",
                     "avg_actual_prefill_tokens_per_request"):
            # 负值 = 共享前缀组更少
            diff = f"{(a / b - 1) * 100:+.1f}%" if b else "—"
        elif key in ("output_token_throughput_tps", "request_throughput_rps"):
            diff = f"{a / b:.2f}×" if b else "—"
        else:
            diff = f"{(a / b - 1) * 100:+.1f}%" if b else "—"
        rows.append(f"<tr><td class='l'>{label}</td><td>{fmt(a, spec)}</td>"
                    f"<td>{fmt(b, spec)}</td><td>{diff}</td></tr>")
    return "\n".join(rows)


def per_run_table():
    runs = ["run-1", "run-2", "run-3"]
    head = "<tr><th>指标</th>" + "".join(
        f"<th>共享 {r}</th>" for r in runs) + "".join(
        f"<th>分散 {r}</th>" for r in runs) + "</tr>"
    body = []
    for label, key, spec in TABLE_ROWS:
        cells = "".join(
            f"<td>{fmt(SUMMARY['per_run']['shared_prefix'][r][key], spec)}</td>" for r in runs)
        cells += "".join(
            f"<td>{fmt(SUMMARY['per_run']['dispersed_prefix'][r][key], spec)}</td>" for r in runs)
        body.append(f"<tr><td class='l'>{label}</td>{cells}</tr>")
    return f"<table class='small'><caption>逐轮明细（run-1/2/3）</caption>{head}{''.join(body)}</table>"


# ---------------------------------------------------------------- HTML
CSS = f"""
@page {{ size: A4 portrait; margin: 14mm 13mm; }}
@page flow {{ size: A4 landscape; margin: 8mm; }}
body {{ font-family: {FONT_CSS}; font-size: 10.2pt; line-height: 1.5; color: #1a1a1a; }}
h1 {{ font-size: 17pt; margin: 0 0 2mm; }}
h2 {{ font-size: 12.5pt; margin: 4mm 0 2mm; padding-left: 2.5mm; border-left: 3.5px solid #4285f4; }}
h3 {{ font-size: 10.8pt; margin: 3mm 0 1.5mm; }}
p {{ margin: 1.6mm 0; text-align: justify; }}
code, .mono {{ font-family: {MONO_CSS}; font-size: 8.8pt; background: #f4f5f7; padding: 0.4mm 1mm; border-radius: 2px; }}
table {{ width: 100%; border-collapse: collapse; margin: 2mm 0; font-size: 9pt; }}
table.small {{ font-size: 7.9pt; }}
caption {{ caption-side: top; text-align: left; font-weight: 700; font-size: 9pt; margin-bottom: 1mm; }}
th, td {{ border: 0.6px solid #b9bec7; padding: 1.1mm 1.4mm; text-align: right; }}
th {{ background: #eef1f5; text-align: center; font-weight: 700; }}
td.l, th.l {{ text-align: left; }}
.meta {{ color: #555; font-size: 9pt; }}
.box {{ border: 0.8px solid #ccd2da; border-radius: 3px; padding: 2.2mm 3mm; margin: 2mm 0; background: #fbfcfd; }}
.formula {{ text-align: center; margin: 1.5mm 0; }}
.formula img {{ max-width: 100%; }}
ul, ol {{ margin: 1.4mm 0 1.4mm 5mm; padding: 0; }}
li {{ margin: 0.9mm 0; }}
.pageflow {{ page: flow; }}
.pageflow svg {{ width: 100%; }}
.kv {{ display: flex; gap: 6mm; flex-wrap: wrap; }}
.kv div {{ flex: 1 1 45%; }}
.hl {{ background: #fff8e1; }}
.tight {{ font-size: 9pt; }}
"""


def html_main(fpaths):
    def img(k):
        return f'<div class="formula"><img src="{fpaths[k].name}"></div>'

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>

<h1>SGLang 前缀缓存测量与请求流程源码阅读</h1>
<div class="meta">第二次挑战（HW2）· SGLang v0.5.14 · Qwen/Qwen3-0.6B · 报告正文不超过 8 页（本册 6 页）</div>

<h2>0. 实验环境与版本</h2>
<table>
<tr><th class="l">项目</th><th class="l">取值 / 说明</th></tr>
<tr><td class="l">硬件</td><td class="l">CPU 推理环境（x86_64，cgroup 限额 4 核 / 8 GB 内存），<b>无 GPU</b>；
attention backend 自动回退为 <code>torch_native</code></td></tr>
<tr><td class="l">推理框架</td><td class="l">SGLang 0.5.14（<code>SGLANG_USE_CPU_ENGINE=1</code> 启用 CPU 后端）</td></tr>
<tr><td class="l">Ray</td><td class="l">2.56.0（独立于 SGLang 的 Python 环境 <code>/opt/sgl-venv</code>，通过 HTTP 与 SGLang 通信）</td></tr>
<tr><td class="l">模型</td><td class="l">Qwen/Qwen3-0.6B（本地权重 <code>/workspace/models/Qwen3-0.6B</code>）</td></tr>
<tr><td class="l">运行时</td><td class="l">Python 3.11.1 / torch 2.14.1+cpu / transformers 5.8.1 / Ubuntu 24.04</td></tr>
<tr><td class="l">服务启动</td><td class="l"><code>python3 -m sglang.launch_server --model-path /workspace/models/Qwen3-0.6B --device cpu
--mem-fraction-static 0.045 --max-total-tokens 16384 --max-running-requests 16</code>；
日志确认 <code>Tree cache initialized: impl=RadixCache</code>，前缀缓存处于开启状态</td></tr>
</table>

<h2>1. 任务一：测量前缀缓存</h2>
<h3>1.1 实验设计</h3>
<p>构造两组负载，<b>除前缀能否复用之外</b>，模型、输入长度、输出长度、请求顺序与并发数完全一致：</p>
<ul>
<li><b>共享前缀组（shared_prefix）</b>：32 条请求共享同一段 896 token 前缀，各带 128 token 独立后缀，输入共 1024 token。</li>
<li><b>分散前缀组（dispersed_prefix）</b>：32 条请求的前缀两两不同（由不同语料排列生成），输入同样为 1024 token。</li>
</ul>
<p>统一采样参数：<code>temperature=0</code>、<code>max_new_tokens=16</code>、<code>ignore_eos=true</code>、
<code>sampling_seed=2026</code>；接口为原生 <code>POST /generate</code>，直接提交 <code>input_ids</code>，
并使用流式响应（<code>stream=true</code>）；最大并发 8。</p>
<p>每组执行流程（脚本 <code>src/target1/run_benchmark.py</code>）：① 首次实验前用 2 条 32-token 短请求完成服务预热；
② 等待已有请求结束，反复调用 <code>POST /flush_cache</code> 直到返回 <code>Cache flushed.</code> 确认成功；
③ 共享前缀组额外发送一条仅含共享前缀的预热请求，使其进入 RadixCache（不计入结果）；
④ 以信号量限流并发 8 回放 32 条测量请求。两组各重复 3 轮（run-1/2/3）。</p>
<p class="tight">指标定义：<b>成功率</b>=HTTP 200 且完整返回的比例；<b>缓存命中率</b>=Σcached_tokens / Σprompt_tokens
（<code>cached_tokens</code> 取自流式末帧 <code>meta_info</code>）；<b>实际执行 Prefill 的 token 数</b>=Σ(prompt_tokens − cached_tokens)；
<b>TTFT</b>=发出请求到收到首个流式 chunk；<b>TPOT</b>=(E2E − TTFT)/(completion_tokens − 1)；<b>E2E</b>=发出到收到末帧；
p50/p95 采用线性插值百分位。</p>

<h3>1.2 对照主表（三轮 run-1/2/3 的平均）</h3>
<table>
<caption>对照主表（三轮 run-1/2/3 的平均）</caption>
<tr><th class="l">指标</th><th>共享前缀组</th><th>分散前缀组</th><th>共享 vs 分散</th></tr>
{main_table()}
</table>
<p class="tight">「共享 vs 分散」一列：TTFT / TPOT / 端到端延迟与 Prefill token 数为相对变化（<b>负值＝共享前缀组更低</b>），
吞吐为倍数，<b>缓存命中率用百分点（pp）</b>表示。两组 <b>32 条请求均全部成功</b>（成功率 100%），
输入长度 1024、输出长度 16 完全一致；共享前缀组命中率更高、实际 Prefill token 更少，满足完成标准。</p>
<p class="tight">注：共享前缀组单请求平均命中 919.5 token，略多于设计的前缀长度 896。原因是 RadixCache 缓存的是
<b>请求完整序列</b>——先完成的请求会把它的「896 前缀 + 128 后缀」整条写入 radix tree，后续请求的 128 token 后缀
若与某条已缓存序列的后缀开头偶然重合，最长前缀匹配会再向前延伸到 896 之后（实测单请求命中区间 896–1011 token）。
这不是测量误差，而是 radix tree 的真实行为；分散前缀组同理存在 0–27 token 的偶然重合，命中率仅 0.56%，
不影响结论。</p>

<h3>1.3 为什么相同前缀可以复用 K/V：从因果自注意力出发</h3>
{img("attn")}
{img("causal")}
<p>因果掩码 <code>M</code> 使得第 <code>i</code> 个位置的注意力输出只依赖于 <code>x_1..x_i</code>，
而不依赖其后的任何 token。又因为 K、V 是逐位置产生的：</p>
{img("kv")}
<p>所以当两个请求的前 <code>m</code> 个 token 及其位置完全相同（本实验共享前缀 896 token，位置均从 0 开始对齐，
RoPE 的相对位置也一致），它们的 <code>K_{{1:m}}</code>、<code>V_{{1:m}}</code> 逐元素相同，
RadixCache 只要把这 <code>m</code> 个 KV 索引直接交给新请求即可，无需重算。</p>
<p><b>命中后仍需计算哪些 token：</b>① 未命中的 <code>n−m</code> 个 token 的 K 与 V（需要写入缓存）；
② 这 <code>n−m</code> 个 token 的 Q（它们必须 attend 到包括命中部分在内的完整前缀）；
③ 末位的 logits 与第一个输出 token。而已命中的前 <code>m</code> 个 token 的 K、V、Q 全部免算：</p>
{img("prefill")}

<h3 style="page-break-before: always">1.4 TTFT 与 TPOT 为什么呈现不同变化</h3>
<p><b>TTFT</b> 由排队等待 + 本轮 Prefill 计算构成，而 Prefill 的计算量与注意力/MLP 的 token 数成正比，即与
<code>n−m</code> 成正比。共享前缀组 <code>m≈896</code>，实际 Prefill 从 32,583 token 降到 3,344 token
（<b>−89.7%</b>），因此 TTFT p50 由 18.423 s 降到 6.458 s（<b>−64.9%</b>）。
降幅小于 Prefill token 的降幅，是因为 TTFT 中还包含并发 8 下的排队与调度开销这一"固定成本"。</p>
<p><b>TPOT</b> 取决于 Decode 每一步的工作量：每步只有 1 个 query，但要读取该序列<b>全部</b> <code>n</code> 个位置的 K/V。
命中只免去 Prefill 的重算，不改变 <code>n</code>，也不改变每步读 K/V 的量，因此 TPOT 几乎不动：
实测 0.606 s → 0.599 s（<b>−1.1%</b>，属噪声量级）。这正解释了"TTFT 大幅下降、TPOT 基本不变"的现象，
也说明前缀复用是一项<b>只优化 Prefill、不优化 Decode</b> 的技术。</p>
<p>端到端延迟 p50 由 27.682 s 降至 15.482 s（−44.1%），输出吞吐由 4.62 提升到 8.26 token/s（约 1.79×），
均由 Prefill 段节省的时间直接转化而来。</p>

{per_run_table()}
<p class="tight">三轮结果高度一致（命中率 89.79% / 0.56% 三轮完全相同），说明测量具有良好的确定性：
temperature=0 与固定 <code>sampling_seed=2026</code> 下，同一组请求的缓存行为可稳定复现。</p>

<!-- 流程图页由 flow.html 单独渲染后合并，占位 -->

<h2 style="page-break-before: always">3. 任务二：一条 /generate 请求在 v0.5.14 中的主流程（说明）</h2>
<h3>3.1 关键函数与文件位置</h3>
<table class="small">
<tr><th class="l">环节</th><th class="l">函数</th><th class="l">文件 : 位置</th></tr>
<tr><td class="l">HTTP 入口</td><td class="l"><code>generate_request</code></td><td class="l"><code>srt/entrypoints/http_server.py:769</code></td></tr>
<tr><td class="l">分词与请求封装</td><td class="l"><code>TokenizerManager.generate_request</code></td><td class="l"><code>srt/managers/tokenizer_manager.py:576</code></td></tr>
<tr><td class="l">主循环</td><td class="l"><code>Scheduler.event_loop_normal</code></td><td class="l"><code>srt/managers/scheduler.py:1505</code></td></tr>
<tr><td class="l">收包与分发</td><td class="l"><code>process_input_requests</code></td><td class="l"><code>srt/managers/scheduler.py:1628</code></td></tr>
<tr><td class="l">入队</td><td class="l"><code>_add_request_to_queue</code> → <code>waiting_queue.append</code></td><td class="l"><code>srt/managers/scheduler.py:2258 / 2265</code></td></tr>
<tr><td class="l">组 prefill batch</td><td class="l"><code>get_new_batch_prefill</code> / <code>_get_new_batch_prefill_raw</code></td><td class="l"><code>srt/managers/scheduler.py:2702 / 2722</code></td></tr>
<tr><td class="l">刷新待算输入</td><td class="l"><code>Req.init_next_round_input</code></td><td class="l"><code>srt/managers/schedule_batch.py:1123</code></td></tr>
<tr><td class="l">前缀匹配</td><td class="l"><code>RadixCache.match_prefix</code>（<code>match_prefix_for_req</code>）</td><td class="l"><code>srt/mem_cache/radix_cache.py:358</code>（<code>srt/managers/schedule_policy.py:85</code>）</td></tr>
<tr><td class="l">削减本轮计算量</td><td class="l"><code>Req.set_extend_input_len(input_len − len(prefix_indices))</code></td><td class="l">调用 <code>srt/managers/schedule_batch.py:1221</code>；定义 <code>:1525</code></td></tr>
<tr><td class="l">预算准入</td><td class="l"><code>PrefillAdder.add_one_req</code> → <code>can_run_list</code></td><td class="l"><code>srt/managers/schedule_policy.py:858</code></td></tr>
<tr><td class="l">建 batch / 执行</td><td class="l"><code>ScheduleBatch.init_new</code> / <code>run_batch</code></td><td class="l">调用 <code>srt/managers/scheduler.py:2907</code>（定义 <code>schedule_batch.py:1843</code>）/ <code>srt/managers/scheduler.py:3145</code></td></tr>
<tr><td class="l">模型前向</td><td class="l"><code>forward_batch_generation</code> → <code>ModelRunner.forward</code> → <code>_forward_raw</code></td><td class="l"><code>srt/managers/tp_worker.py:65</code> / <code>srt/model_executor/model_runner.py:2896 / 2987</code></td></tr>
<tr><td class="l">结果处理</td><td class="l"><code>process_batch_result</code></td><td class="l"><code>srt/managers/scheduler.py:3367</code></td></tr>
<tr><td class="l">完成写回</td><td class="l"><code>release_kv_cache</code> → <code>RadixCache.cache_finished_req</code></td><td class="l"><code>srt/mem_cache/common.py:629</code> → <code>srt/mem_cache/radix_cache.py:438</code></td></tr>
<tr><td class="l">未完成写回</td><td class="l"><code>maybe_cache_unfinished_req</code> → <code>cache_unfinished_req</code></td><td class="l"><code>srt/mem_cache/common.py:113</code> → <code>srt/mem_cache/radix_cache.py:485</code></td></tr>
<tr><td class="l">流式输出</td><td class="l"><code>handle_loop</code> → <code>_handle_batch_output</code> → <code>_wait_one_response</code></td><td class="l"><code>srt/managers/tokenizer_manager.py:1824 / 1839 / 1425</code></td></tr>
<tr><td class="l">流式粒度</td><td class="l"><code>stream_interval</code> 判定</td><td class="l"><code>srt/managers/scheduler_components/output_streamer.py:324</code></td></tr>
</table>

<h3>3.2 四个问题的回答</h3>
<p><b>① 请求如何进入等待队列。</b>HTTP 层 <code>http_server.py:769</code> 收到 <code>/generate</code> 后进入
<code>TokenizerManager.generate_request</code>（<code>tokenizer_manager.py:576</code>）：先做参数归一化，
再把文本/ids 分词成 <code>input_ids</code>，随后 <code>_send_one_request</code> 经 ZMQ IPC 把
<code>TokenizedGenerateReqInput</code> 发给 Scheduler 进程。Scheduler 在
<code>event_loop_normal</code>（<code>scheduler.py:1505</code>）每一轮先 <code>recv_requests()</code>，
再由 <code>process_input_requests</code>（1628）分发，最终 <code>_add_request_to_queue</code>（2258）
把请求 <code>append</code> 进 <code>waiting_queue</code>（2265）并记录入队时刻；此后请求才参与组 batch。</p>

<p><b>② 前缀匹配如何减少本轮 Prefill token。</b><code>get_new_batch_prefill</code>（2702）遍历
<code>waiting_queue</code> 时，先调用 <code>req.init_next_round_input(self.tree_cache)</code>（2847），
其内部（<code>schedule_batch.py:1166</code>）调用 <code>RadixCache.match_prefix</code>
（<code>radix_cache.py:358</code>）在 radix tree 上做最长前缀匹配（key 先按 <code>page_size</code> 对齐），
返回 <code>prefix_indices</code>——即已驻留的 KV cache 槽位索引；随后
<code>set_extend_input_len(input_len − len(prefix_indices))</code>（<code>schedule_batch.py:1221</code>）
把本轮真正需要计算的 token 数收缩到未命中的那一段。之后 <code>PrefillAdder.add_one_req</code>
（<code>schedule_policy.py:858</code>）按 <code>extend_input_len + max_new_tokens + page_size</code>
校验剩余 token/内存预算，通过者进入 <code>can_run_list</code>，由 <code>ScheduleBatch.init_new</code> 成批。
本实验中共享前缀组因此把合计 Prefill 从 32,583 token 压到 3,344 token。</p>

<p><b>③ 新产生的 KV 如何写回缓存。</b>Prefill/Decode 在
<code>ModelRunner._forward_raw</code>（<code>model_runner.py:2987</code>）中执行，新算出的 K/V 写入
<code>token_to_kv_pool_allocator</code> 分配的槽位，并通过 <code>req_to_token</code> 建立
请求→ token → 槽位的映射。批次返回后 <code>process_batch_result</code>（3367）分两种情况处理：
请求结束走 <code>release_kv_cache</code>（<code>common.py:629</code>）→
<code>RadixCache.cache_finished_req</code>（<code>radix_cache.py:438</code>），以
<code>(origin_input_ids + output_ids)</code> 为 key 把 KV 索引插入 radix tree，
并把与树中已有节点重复的部分 <code>kv_indices[cache_protected_len : prefix_len]</code> 以及未对齐的尾部释放；
请求未结束（chunked prefill 或发生抢占）则走 <code>maybe_cache_unfinished_req</code>（<code>common.py:113</code>）
→ <code>cache_unfinished_req</code>（<code>radix_cache.py:485</code>）先把已算部分落树。
插入期间用 <code>inc_lock_ref / dec_lock_ref</code> 保护正在被引用的节点不被 LRU 驱逐。</p>

<p><b>④ 生成结果如何流式返回。</b>Scheduler 侧按 <code>stream_interval</code>（默认 1，即每生成 1 个 token，
见 <code>output_streamer.py:324</code>）把增量输出经 IPC 发回 TokenizerManager；
<code>handle_loop</code>（1824）→ <code>_handle_batch_output</code>（1839）把增量写入
<code>rid_to_state[rid].out_list</code> 并 <code>set()</code> 对应 event；
<code>generate_request</code> 中的 <code>_wait_one_response</code>（1425）被唤醒后逐个
<code>yield</code>，HTTP 层以 SSE（<code>data: {{...}}</code>）逐帧下发给客户端，
末帧 <code>meta_info</code> 携带 <code>prompt_tokens / cached_tokens / completion_tokens / e2e_latency</code>——
本报告的 <code>cached_tokens</code> 与命中率正是从这里采集的。</p>

<h2>4. 结论与结果索引</h2>
<p>在保持输入/输出长度、请求顺序与并发数一致的前提下，开启 RadixCache 的共享前缀负载把实际 Prefill token
降低 89.7%、TTFT p50 降低 64.9%、端到端延迟 p50 降低 44.1%、输出吞吐提升约 1.79×，而 TPOT 基本不变（−1.1%），
与"前缀复用只削减 Prefill 计算、不改变 Decode 每步读 K/V 量"的理论分析一致。</p>
<table class="small">
<tr><th class="l">报告中的表格/数字</th><th class="l">对应的原始结果文件</th></tr>
<tr><td class="l">1.2 主表（三轮均值）</td><td class="l"><code>results/target1/summary.json</code> 的 <code>mean</code> 字段，由 <code>src/target1/aggregate.py</code> 汇总</td></tr>
<tr><td class="l">1.4 逐轮明细</td><td class="l"><code>results/target1/&#123;shared_prefix,dispersed_prefix&#125;/run-1|2|3/summary.json</code></td></tr>
<tr><td class="l">逐请求 TTFT/TPOT/cached_tokens</td><td class="l"><code>results/target1/&#123;组&#125;/run-N/per_request.jsonl</code>（每行一条请求）</td></tr>
<tr><td class="l">执行日志（含 flush_cache 确认、预热）</td><td class="l"><code>results/target1/&#123;组&#125;/run-N.log</code></td></tr>
</table>
</body></html>"""


def html_flow():
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body {{ margin: 0; background: #fff; }}
svg {{ display: block; }}
</style></head>
<body>
{FLOW_SVG}
</body></html>"""


def flow_page_pdf(png_path, pdf_path):
    """把流程图截图放到横向 A4 PDF 页（reportlab）。"""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas as rl_canvas
    from PIL import Image

    page_w, page_h = landscape(A4)
    c = rl_canvas.Canvas(str(pdf_path), pagesize=(page_w, page_h))
    img = Image.open(png_path)
    iw, ih = img.size
    margin = 14
    avail_w, avail_h = page_w - 2 * margin, page_h - 2 * margin
    scale = min(avail_w / iw, avail_h / ih)
    w, h = iw * scale, ih * scale
    x = (page_w - w) / 2
    y = (page_h - h) / 2
    c.drawImage(str(png_path), x, y, width=w, height=h)
    c.showPage()
    c.save()


def chromium_pdf(html_path, pdf_path):
    subprocess.run([
        "chromium", "--headless", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", f"file://{html_path}",
    ], check=True, capture_output=True, timeout=300)


def main():
    fpaths = render_formulas()
    (BUILD / "main.html").write_text(html_main(fpaths), encoding="utf-8")
    (BUILD / "flow.html").write_text(html_flow(), encoding="utf-8")
    chromium_pdf(BUILD / "main.html", BUILD / "main.pdf")
    # 流程图：Chromium 高分辨率截图 -> reportlab 生成横向 A4 页
    subprocess.run([
        "chromium", "--headless", "--disable-gpu", "--no-sandbox",
        "--window-size=1180,830", "--force-device-scale-factor=2",
        f"--screenshot={BUILD / 'flow.png'}", f"file://{BUILD / 'flow.html'}",
    ], check=True, capture_output=True, timeout=300)
    flow_page_pdf(BUILD / "flow.png", BUILD / "flow.pdf")

    from pypdf import PdfReader, PdfWriter
    main_pdf = PdfReader(str(BUILD / "main.pdf"))
    flow_pdf = PdfReader(str(BUILD / "flow.pdf"))
    writer = PdfWriter()
    # 流程图插到"任务二说明"之前
    insert_at = min(3, len(main_pdf.pages) - 1)
    for i, page in enumerate(main_pdf.pages):
        if i == insert_at:
            writer.add_page(flow_pdf.pages[0])
        writer.add_page(page)
    out = ROOT / "report.pdf"
    with open(out, "wb") as f:
        writer.write(f)
    print("wrote", out, "pages:", len(writer.pages))


if __name__ == "__main__":
    main()
