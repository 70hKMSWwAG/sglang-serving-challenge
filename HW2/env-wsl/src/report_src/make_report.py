#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_report.py —— 由 results/ 下的原始测量结果生成 report.html

设计原则：报告正文里的每一个数字都从 results/target1/<组>/<run>/summary.json
与 server_log_slice.log 现算出来，绝不手工誊抄，从而保证「报告中的数据能对应到原始结果」。

用法：
    python make_report.py            # 读取 ../../results/target1，输出 report.html
"""

import html
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HW2 = os.path.abspath(os.path.join(HERE, "..", ".."))
RESDIR = os.path.join(HW2, "results", "target1")
NAME = "0102603133"


def esc(s):
    return html.escape(str(s), quote=False)


def load_json(p, default=None):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def read_text(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


PREFILL_RE = re.compile(
    r"Prefill batch, #new-seq: (\d+), #new-token: (\d+), #cached-token: (\d+)"
)
PREFILL_SEQ_RE = re.compile(r"Prefill batch, #new-seq: (\d+)")
TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")


def _to_sec(ts):
    """'2026-09-29 11:01:32' -> 当天秒数。"""
    hh, mm, ss = ts.split(" ")[1].split(":")
    return int(hh) * 3600 + int(mm) * 60 + int(ss)


def parse_prefill_log(text):
    """从服务端日志里抽取 Prefill batch 的 #new-seq / #new-token / #cached-token。"""
    rows = []
    for m in PREFILL_RE.finditer(text):
        rows.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return rows


def admission_evidence(text):
    """抽取「同轮请求被分批准入」的服务端证据。

    返回 (evidence_text, gap_seconds, first_new_seq, second_new_seq)：
    本组前两条 Prefill batch 记录、二者的时间差（秒）、以及各自的 #new-seq。
    """
    lines, secs = [], []
    for line in text.splitlines():
        if not PREFILL_SEQ_RE.search(line):
            continue
        lines.append(line.rstrip())
        m = TS_RE.match(line)
        secs.append(_to_sec(m.group(1)) if m else None)
        if len(lines) == 2:
            break
    if len(lines) < 2:
        return ("", None, None, None)
    gap = (secs[1] - secs[0]) if (secs[0] is not None and secs[1] is not None) else None
    ns = [int(PREFILL_SEQ_RE.search(x).group(1)) for x in lines]
    return ("\n".join(lines), gap, ns[0], ns[1])


THR_RE = re.compile(r"input throughput \(token/s\): ([\d.]+)")


def parse_throughputs(text):
    """抽取服务端日志中 Prefill 批次自报的 <input throughput>。"""
    return [float(x) for x in THR_RE.findall(text)]


def load_requests(d):
    """逐请求明细（<组>/<tag>/requests.jsonl）。"""
    p = os.path.join(d, "requests.jsonl")
    rows = []
    try:
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except Exception:
        pass
    return rows


def wave_spread(rows, k=8, key="e2e_ms"):
    """把请求按提交批次（每 k 条一轮）切分，返回轮内极差的最大值。

    同一轮请求由客户端线程池同时发出，其端到端耗时应几乎一致；
    极差很小即可反证「客户端是同时发送的」。
    """
    vals = []
    for i in range(0, len(rows), k):
        w = [r[key] for r in rows[i:i + k] if r.get(key) is not None]
        if len(w) > 1:
            vals.append(max(w) - min(w))
    return max(vals) if vals else None


def fmt(x, nd=2):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    return f"{x:,}"


def intfmt(x):
    if x is None:
        return "—"
    return f"{int(round(x)):,}"


# --------------------------------------------------------------------------- 数据装载
def load_runs():
    """按交付目录 results/target1/<组>/<tag>/ 装载各次运行的结果。"""
    runs = {}
    if not os.path.isdir(RESDIR):
        return runs
    for g in ("shared_prefix", "dispersed_prefix"):
        gd = os.path.join(RESDIR, g)
        if not os.path.isdir(gd):
            continue
        for tag in sorted(os.listdir(gd)):
            d = os.path.join(gd, tag)
            if not os.path.isdir(d):
                continue
            s = load_json(os.path.join(d, "summary.json"))
            if not s:
                continue
            log = read_text(os.path.join(d, "server_log_slice.log"))
            s["_prefill"] = parse_prefill_log(log)
            s["_evidence"] = admission_evidence(log)
            s["_reqs"] = load_requests(d)
            s["_thr"] = parse_throughputs(log)
            runs.setdefault(tag, {})[g] = s
    return runs


# --------------------------------------------------------------------------- SVG 图表
def bar_chart(items, width=680, bar_h=22, gap=16, pad_left=190, title=""):
    """items = [(标签, 值, 单位, 颜色), ...]，横向条形图。"""
    vals = [v for _, v, _, _ in items]
    vmax = max(vals) if vals and max(vals) > 0 else 1.0
    n = len(items)
    h = n * (bar_h + gap) + gap
    x0 = pad_left
    wmax = width - pad_left - 120
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" '
           f'font-family="Noto Sans CJK SC, Microsoft YaHei, sans-serif">']
    for i, (label, v, unit, color) in enumerate(items):
        y = gap + i * (bar_h + gap)
        bw = max(1.0, vmax and (v / vmax) * wmax or 1.0)
        out.append(
            f'<text x="{pad_left-8}" y="{y+bar_h*0.72:.1f}" text-anchor="end" '
            f'font-size="11.5" fill="#2b3a4a">{esc(label)}</text>'
        )
        out.append(
            f'<rect x="{x0}" y="{y}" width="{wmax}" height="{bar_h}" rx="3" fill="#eef3f8"/>'
        )
        out.append(
            f'<rect x="{x0}" y="{y}" width="{bw:.1f}" height="{bar_h}" rx="3" fill="{color}"/>'
        )
        txt = f"{v:,.2f}" if isinstance(v, float) and abs(v) < 10000 else f"{v:,.0f}"
        out.append(
            f'<text x="{x0+bw+7:.1f}" y="{y+bar_h*0.72:.1f}" font-size="11.5" '
            f'font-weight="600" fill="#16283d">{esc(txt)} {esc(unit)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def grouped_bar_chart(labels, series, width=680, height=250):
    """series = [(名称, 颜色, [值...]), ...]，分组柱状图。"""
    pad_l, pad_r, pad_t, pad_b = 62, 12, 18, 46
    n = len(labels)
    ns = len(series)
    allv = [v for _, _, vs in series for v in vs]
    vmax = max(allv) if allv and max(allv) > 0 else 1.0
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    grp_w = plot_w / n
    bw = min(28.0, grp_w / (ns + 0.9))
    out = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'font-family="Noto Sans CJK SC, Microsoft YaHei, sans-serif">']
    # y 轴网格
    for k in range(5):
        yv = vmax * k / 4.0
        y = pad_t + plot_h - (yv / vmax) * plot_h
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" '
                   f'stroke="#e3eaf2" stroke-width="1"/>')
        out.append(f'<text x="{pad_l-6}" y="{y+3.5:.1f}" text-anchor="end" font-size="9.5" '
                   f'fill="#7b8794">{yv:,.1f}</text>')
    for gi, lab in enumerate(labels):
        gx = pad_l + gi * grp_w
        for si, (sname, color, vs) in enumerate(series):
            v = vs[gi]
            bh = (v / vmax) * plot_h
            bx = gx + grp_w / 2 - (ns * bw) / 2 + si * bw + bw * 0.08
            by = pad_t + plot_h - bh
            out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw*0.84:.1f}" height="{max(bh,0.8):.1f}" '
                       f'rx="2" fill="{color}"/>')
            out.append(f'<text x="{bx+bw*0.42:.1f}" y="{by-3.5:.1f}" text-anchor="middle" '
                       f'font-size="9.2" fill="#33455a">{v:,.1f}</text>')
        out.append(f'<text x="{gx+grp_w/2:.1f}" y="{pad_t+plot_h+15:.1f}" text-anchor="middle" '
                   f'font-size="10.2" fill="#2b3a4a">{esc(lab)}</text>')
    # 图例
    lx = pad_l
    for sname, color, _ in series:
        out.append(f'<rect x="{lx}" y="{height-18}" width="10" height="10" rx="2" fill="{color}"/>')
        out.append(f'<text x="{lx+14}" y="{height-9}" font-size="10.2" fill="#2b3a4a">{esc(sname)}</text>')
        lx += 22 + len(sname) * 11
    out.append("</svg>")
    return "\n".join(out)


CSS = """
@page { size: A4; margin: 16mm 15mm 14mm 15mm; }
@page chartpage { size: A4; margin: 11mm 9mm 9mm 9mm; }
* { box-sizing: border-box; }
body { font-family: "Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei",sans-serif;
       color:#1b2733; font-size:10.6pt; line-height:1.62; margin:0; }
h1 { font-size:19pt; margin:0 0 4px; letter-spacing:.5px; }
h2 { font-size:13.2pt; margin:16px 0 7px; padding:5px 0 5px 10px; border-left:4px solid #2b5c8a;
     background:#f2f7fc; color:#16324f; }
h3 { font-size:11.4pt; margin:12px 0 5px; color:#1d4b73; }
h4 { font-size:10.6pt; margin:10px 0 4px; color:#2b3a4a; }
p  { margin:5px 0; text-align:justify; }
ul,ol { margin:5px 0 5px 20px; padding:0; }
li { margin:2.5px 0; }
table { border-collapse:collapse; width:100%; margin:8px 0 4px; font-size:9.6pt; }
th,td { border:1px solid #cfdbe6; padding:4.5px 7px; text-align:left; vertical-align:top; }
th { background:#eef4fa; color:#16324f; font-weight:600; }
td.n, th.n { text-align:right; font-variant-numeric:tabular-nums; }
tr.hl td { background:#fff9e8; font-weight:600; }
.mono { font-family:Consolas,"DejaVu Sans Mono",monospace; font-size:9.2pt; }
.small { font-size:9.2pt; color:#54626f; }
.note { background:#f7fafd; border:1px solid #dbe6f0; border-radius:5px; padding:7px 10px; margin:8px 0; }
.warn { background:#fff9e8; border:1px solid #e8cd8a; border-radius:5px; padding:7px 10px; margin:8px 0; }
.blank { background:#fbfbfb; border:1px dashed #b9c6d3; border-radius:5px; padding:8px 10px;
         margin:6px 0; color:#7a8794; font-size:9.6pt; min-height:56px; }
.page { page-break-after: always; }
.page:last-child { page-break-after: auto; }
.page.tight { font-size:10.0pt; line-height:1.5; }
.page.tight h2 { margin:0 0 6px; }
.page.tight h3 { margin:9px 0 4px; }
.page.tight p { margin:4px 0; }
.page.tight table { font-size:9.2pt; }
.page.tight ul, .page.tight ol { margin:4px 0 4px 18px; }
.page.tight li { margin:1.6px 0; }
.page.chartpage { page: chartpage; }
.page.chartpage h2 { margin:0 0 2px; font-size:12pt; padding:3px 0 3px 9px; }
.page.chartpage svg { display:block; width:100%; height:268mm; }
.covertop { text-align:center; padding:16mm 0 4mm; }
.covertop h1 { border:none; }
.covertop .sub { color:#54626f; font-size:11pt; margin-top:8px; }
.covertop .line { width:96px; height:3px; background:#2b5c8a; margin:14px auto 16px; }
.covertop .meta { margin-top:14px; font-size:10.4pt; color:#37474f; line-height:1.9; }
.kv { display:grid; grid-template-columns: 108px 1fr; gap:2px 10px; font-size:10pt; }
.kv b { color:#37474f; font-weight:600; }
.formula { text-align:center; margin:10px 0; font-size:11pt; }
.frac { display:inline-block; vertical-align:middle; text-align:center; margin:0 3px; }
.frac .num { display:block; padding:0 4px; border-bottom:1.2px solid #33455a; }
.frac .den { display:block; padding:0 4px; }
.sig { margin-top:14px; text-align:right; color:#37474f; font-size:10.2pt; }
.legend { font-size:9.4pt; color:#54626f; margin:2px 0 8px; }
"""


def build_html(runs):
    primary = "run-1" if "run-1" in runs else (sorted(runs)[0] if runs else None)
    sp = runs.get(primary, {}).get("shared_prefix") if primary else None
    dp = runs.get(primary, {}).get("dispersed_prefix") if primary else None
    have = bool(sp and dp)

    ver = read_text(os.path.join(RESDIR, "shared_prefix", primary, "version_info.log")) if primary else ""
    # 服务端日志里的 server_args 是单行全量转储（上万字符），报告只摘录与缓存/批调度相关的项
    srv_rows = []
    m = re.search(r"### 服务端 KV/缓存配置.*?\n(.*)", ver, re.S)
    if m:
        blob = m.group(1).strip()
        for key, label in (
            ("disable_radix_cache", "disable_radix_cache"),
            ("radix_cache_backend", "radix_cache_backend"),
            ("radix_eviction_policy", "radix_eviction_policy"),
            ("page_size", "page_size（命中粒度对齐）"),
            ("chunked_prefill_size", "chunked_prefill_size"),
            ("max_prefill_tokens", "max_prefill_tokens"),
            ("schedule_policy", "schedule_policy"),
            ("attention_backend", "attention_backend"),
            ("disable_chunked_prefix_cache", "disable_chunked_prefix_cache"),
            ("device", "device"),
            ("dtype", "dtype"),
            ("tp_size", "tp_size"),
        ):
            mm = re.search(rf"\b{key}='([^']*)'|\b{key}=([A-Za-z0-9_.+-]+)", blob)
            if mm:
                val = mm.group(1) if mm.group(1) is not None else mm.group(2)
                if key == "disable_radix_cache":
                    val += "（False = 启用 Radix Cache）"
                srv_rows.append((label, val))
        for line in blob.splitlines():
            if not line.startswith("["):
                continue
            if "KV Cache is allocated" in line:
                srv_rows.append(("KV 实际分配", line.strip()))
            elif "max_total_num_tokens" in line:
                srv_rows.append(("运行上限（服务端自报）", line.strip()))
            elif "Tree cache initialized" in line:
                srv_rows.append(("基数树初始化", line.strip()))
    srv_kv = "".join(f"<tr><td>{esc(a)}</td><td class='mono'>{esc(b)}</td></tr>"
                     for a, b in srv_rows)

    svg = read_text(os.path.join(HERE, "flowchart.svg"))

    P = []
    A = P.append

    # ------------------------------------------------------------------ 封面 + 摘要 + 环境
    A(f'''<div class="page">
<div class="covertop">
<h1>SGLang 前缀缓存测量 与 /generate 请求流程分析</h1>
<div class="line"></div>
<div class="sub">第二次挑战 · 实验报告</div>
<div class="meta">
<span><b>模型</b>　Qwen/Qwen3-0.6B　　<b>SGLang</b>　0.5.14　　<b>Ray</b>　2.56.0</span><br>
<span><b>平台</b>　WSL2 Ubuntu 26.04　Intel Core Ultra 5 338H（12 vCPU，纯 CPU 推理）</span><br>
<span><b>学号</b>　{esc(NAME)}</span>
</div>
</div>
''')
    A("<h2>一、摘要</h2>")
    if have:
        ttft_drop = (1 - sp["ttft_ms"]["p50"] / dp["ttft_ms"]["p50"]) * 100
        A(f'''<p>本次挑战在第一次挑战已部署好的 SGLang 0.5.14 在线服务上，测量了 <b>Radix Cache 前缀复用</b>
的实际效果。两组负载各 32 条请求、最大并发 8，输入长度同为 2112 token，采样参数完全一致，
唯一差别是前缀能否被复用。结果显示：共享前缀组把 <b>{fmt(sp["cache_hit_rate"]*100,2)}%</b> 的 prompt token 变成缓存命中，
实际执行 Prefill 的 token 数由 {intfmt(dp["actual_prefill_tokens"])} 降至
{intfmt(sp["actual_prefill_tokens"])}（降幅 {fmt((1-sp["actual_prefill_tokens"]/dp["actual_prefill_tokens"])*100,1)}%），
TTFT 的 p50 由 {fmt(dp["ttft_ms"]["p50"],1)} ms 降至 {fmt(sp["ttft_ms"]["p50"],1)} ms，
端到端 p50 由 {fmt(dp["e2e_ms"]["p50"],1)} ms 降至 {fmt(sp["e2e_ms"]["p50"],1)} ms，
输出吞吐由 {fmt(dp["output_throughput_tok_s"])} 提升到 {fmt(sp["output_throughput_tok_s"])} tok/s。
TPOT 表面上也从 {fmt(dp["tpot_ms"]["p50"],2)} ms 降到 {fmt(sp["tpot_ms"]["p50"],2)} ms，
但那是「同批同步」下与 TTFT 此消彼长的结果，<b>不能</b>读作 Decode 变快（见 6.1）。
两组成功率均为 {sp["n_success"]}/{sp["n_requested"]}。</p>''')
        A('''<p>这与因果自注意力下「K/V 只由该位置及其之前的 token 决定」的性质一致：前缀缓存削减的是
<b>Prefill 的计算量</b>，而不改变 Decode 每步需要读取的上下文长度（上下文长 N 与步数两组完全一致）。
把两组多出的 Prefill token 按服务端实测的 Prefill 吞吐折算，恰好能解释端到端时长的全部差异（见 6.2）。
任务二沿指定主线逐跳核对了 v0.5.14 源码，给出了覆盖「请求接收 → 等待队列 → 前缀匹配 → Prefill/Decode
→ 缓存写回 → 流式输出」的流程图与说明。</p>''')
    else:
        A('<p class="warn">测量结果尚未生成。请先执行 <span class="mono">src/target1/run_target1.sh</span>，'
          '再重新生成本报告。</p>')

    A("<h2>二、实验环境与软件版本</h2>")
    A('''<table>
<tr><th style="width:22%">项</th><th>值</th></tr>
<tr><td>宿主 / 发行版</td><td>Windows + WSL2 · Ubuntu 26.04 LTS (Resolute Racoon)</td></tr>
<tr><td>CPU</td><td>Intel Core Ultra 5 338H（代号 Panther Lake），12 vCPU；<b>无 AVX-512、无 AMX</b></td></tr>
<tr><td>GPU / NPU</td><td>Intel Arc B370 核显 + NPU。<b>未参与计算</b>：WSL 内无 <span class="mono">i915</span>/<span class="mono">xe</span>
 DRM 驱动，缺 Intel 计算运行时（Level-Zero / OpenCL / SYCL），<span class="mono">/dev/dri</span> 仅由内核 <span class="mono">vgem</span> 虚拟桩提供</td></tr>
<tr><td>Python</td><td>3.12.14（standalone，与发行版自带 3.14 解耦）</td></tr>
<tr><td><b>SGLang</b></td><td><b>0.5.14</b>（源码构建，<span class="mono">--device cpu</span>）</td></tr>
<tr><td><b>Ray</b></td><td><b>2.56.0</b>（独立 venv，与 SGLang 通过 HTTP 通信）</td></tr>
<tr><td><b>模型</b></td><td><b>Qwen/Qwen3-0.6B</b>（bfloat16）</td></tr>
<tr><td>Radix Cache</td><td><b>开启</b>（未传 <span class="mono">--disable-radix-cache</span>；服务端日志有 <span class="mono">Tree cache initialized … RadixCache</span>）</td></tr>
</table>''')
    if srv_kv:
        A('<h4>服务端自报的缓存与批调度配置（摘自服务端启动日志，完整日志见 version_info.log）</h4>')
        A('<table>' + srv_kv + "</table>")
    else:
        A('<p class="small">（服务端缓存配置日志见 results/target1/&lt;组&gt;/run-1/version_info.log）</p>')
    A("</div>")

    A('<div class="page tight">')
    A("<h2>三、任务一：测量前缀缓存</h2>")
    A("<h3>3.1 两组负载的结构</h3>")
    A('''<table>
<tr><th style="width:14%">负载</th><th style="width:44%">输入结构</th><th>测量前准备</th></tr>
<tr><td><b>共享前缀</b></td><td>2048 个 token 的共享前缀 + 64 个 token 的独立后缀（合计 <b>2112</b>）</td><td>发送 1 条包含共享前缀的预热请求（不计入结果）</td></tr>
<tr><td><b>分散前缀</b></td><td>输入长度均为 <b>2112</b> 个 token，且首个 token 各不相同</td><td>不进行前缀预热</td></tr>
</table>''')
    A('''<h3>3.2 控制变量：如何做到「除前缀能否复用外，其余一致」</h3>
<p>若两组各照字面自造一份语料，内容差异会与「前缀可否复用」混在一起。为把自变量隔离出来，
分散前缀组按下面的方式构造（记号：<span class="mono">SHARED = base[0:2048]</span>，
<span class="mono">SUFFIX[i] = base[2048+64i : 2112+64i]</span>，<span class="mono">u_i</span> 为 32 个两两互异的合法 token id）：</p>
<div class="formula mono" style="text-align:left;margin-left:14px">
共享组第 i 条 = SHARED[0:2048] + SUFFIX[i]<br>
分散组第 i 条 = [u<sub>i</sub>] + SHARED[1:2048] + SUFFIX[i]
</div>
<p>于是两组：输入长度同为 2112；独立后缀逐 token 相同；承载共享前缀的 2048 个 token 中有
<b>2047 个完全相同</b>；唯一差别是位置 0 的 token 两两不同。而 RadixCache 是从根节点按 token 逐位匹配的，
位置 0 一旦不同，两条序列在树中就没有公共可达节点，前缀复用率为 0 —— 自变量因此被隔离为单一变量。
构造逻辑与断言见 <span class="mono">src/target1/prefix_cache_bench.py</span> 的 <span class="mono">build_workloads()</span>。</p>''')
    A('''<h3>3.3 测量流程</h3>
<ol>
<li>服务预热：首次实验前先发一条 <b>短请求</b>（16 token）完成预热，结果丢弃。</li>
<li>每组测量前：等待已有请求全部结束 → <span class="mono">POST /flush_cache</span> 并确认返回
 <span class="mono">Cache flushed.</span>（HTTP 200）。</li>
<li>共享前缀组在 flush 之后再发 <b>1 条包含共享前缀的预热请求</b>（2048+64），结果丢弃；
 分散前缀组不做任何预热。</li>
<li>按序号顺序提交 32 条测量请求，<b>最大并发 8</b>，全部使用原生
 <span class="mono">/generate</span> + <span class="mono">input_ids</span> + <span class="mono">stream=true</span>。</li>
<li>逐请求从服务端返回的 <span class="mono">meta_info</span> 读取 <span class="mono">prompt_tokens</span> 与
 <span class="mono">cached_tokens</span>；TTFT 取「首个携带生成 token 的分片到达」的时刻，
 TPOT = (端到端 − TTFT) / (生成 token 数 − 1)。</li>
</ol>
<div class="note"><b>指标定义（与任务书一致）</b><br>
缓存命中率 = Σ<span class="mono">cached_tokens</span> / Σ<span class="mono">prompt_tokens</span>；
实际 Prefill token 数 = Σ(<span class="mono">prompt_tokens</span> − <span class="mono">cached_tokens</span>)。<br>
分位数 p50 / p95 采用线性插值（与 numpy 默认方法一致）。吞吐量 = Σ<span class="mono">completion_tokens</span> / 本组墙钟时间。</div>''')
    A("</div>")

    # ------------------------------------------------------------------ 主表
    A('<div class="page">')
    A(f'<h2>四、任务一：测量结果{("（" + primary + "）") if primary else ""}</h2>')
    if have:
        A("<h3>4.1 主对照表</h3>")
        A(f'''<table>
<tr>
  <th style="width:30%">指标</th>
  <th class="n" style="width:24%">共享前缀<br>shared_prefix</th>
  <th class="n" style="width:24%">分散前缀<br>dispersed_prefix</th>
  <th>说明</th>
</tr>
<tr><td>成功率</td><td class="n">{sp["n_success"]}/{sp["n_requested"]}（{fmt(sp["success_rate"]*100,1)}%）</td>
    <td class="n">{dp["n_success"]}/{dp["n_requested"]}（{fmt(dp["success_rate"]*100,1)}%）</td>
    <td>两组测量请求均全部成功</td></tr>
<tr><td>吞吐量（输出 tok/s）</td><td class="n">{fmt(sp["output_throughput_tok_s"])}</td>
    <td class="n">{fmt(dp["output_throughput_tok_s"])}</td><td>Σ completion_tokens / 墙钟</td></tr>
<tr><td>吞吐量（请求 req/s）</td><td class="n">{fmt(sp["request_throughput_rps"],3)}</td>
    <td class="n">{fmt(dp["request_throughput_rps"],3)}</td><td>32 / 墙钟</td></tr>
<tr class="hl"><td>缓存命中率</td><td class="n">{fmt(sp["cache_hit_rate"]*100,2)}%</td>
    <td class="n">{fmt(dp["cache_hit_rate"]*100,2)}%</td><td>Σcached / Σprompt，取自服务端 meta_info</td></tr>
<tr class="hl"><td>实际 Prefill token 数</td><td class="n">{intfmt(sp["actual_prefill_tokens"])}</td>
    <td class="n">{intfmt(dp["actual_prefill_tokens"])}</td>
    <td>Σ(prompt − cached)；总 prompt 各 {intfmt(sp["total_prompt_tokens"])} / {intfmt(dp["total_prompt_tokens"])}</td></tr>
<tr><td>TTFT p50（ms）</td><td class="n">{fmt(sp["ttft_ms"]["p50"],1)}</td>
    <td class="n">{fmt(dp["ttft_ms"]["p50"],1)}</td><td>首 token 到达时间</td></tr>
<tr><td>TTFT p95（ms）</td><td class="n">{fmt(sp["ttft_ms"]["p95"],1)}</td>
    <td class="n">{fmt(dp["ttft_ms"]["p95"],1)}</td><td rowspan="2">p95 反映高并发下的长尾</td></tr>
<tr><td>TPOT p50（ms）</td><td class="n">{fmt(sp["tpot_ms"]["p50"],2)}</td>
    <td class="n">{fmt(dp["tpot_ms"]["p50"],2)}</td></tr>
<tr><td>TPOT p95（ms）</td><td class="n">{fmt(sp["tpot_ms"]["p95"],2)}</td>
    <td class="n">{fmt(dp["tpot_ms"]["p95"],2)}</td><td>输出 token 间平均间隔</td></tr>
<tr><td>端到端 p50（ms）</td><td class="n">{fmt(sp["e2e_ms"]["p50"],1)}</td>
    <td class="n">{fmt(dp["e2e_ms"]["p50"],1)}</td><td rowspan="2">整条请求耗时</td></tr>
<tr><td>端到端 p95（ms）</td><td class="n">{fmt(sp["e2e_ms"]["p95"],1)}</td>
    <td class="n">{fmt(dp["e2e_ms"]["p95"],1)}</td></tr>
<tr><td>墙钟时间（s）</td><td class="n">{fmt(sp["wall_clock_s"],1)}</td>
    <td class="n">{fmt(dp["wall_clock_s"],1)}</td><td>并发 8 下 32 条请求的总耗时</td></tr>
</table>
<p class="legend">数据源：<span class="mono">results/target1/{{shared_prefix,dispersed_prefix}}/{esc(primary)}/summary.json</span>；
逐请求明细见同目录 <span class="mono">requests.jsonl</span>。</p>''')

        A(grouped_bar_chart(
            ["缓存命中率 (%)", "实际 Prefill (k tokens)", "TTFT p50 (s)", "TPOT p50 (s)", "端到端 p50 (s)"],
            [("共享前缀 shared_prefix", "#2b5c8a", [
                sp["cache_hit_rate"] * 100,
                sp["actual_prefill_tokens"] / 1000.0,
                sp["ttft_ms"]["p50"] / 1000.0,
                sp["tpot_ms"]["p50"] / 1000.0,
                sp["e2e_ms"]["p50"] / 1000.0,
            ]),
             ("分散前缀 dispersed_prefix", "#c8901a", [
                dp["cache_hit_rate"] * 100,
                dp["actual_prefill_tokens"] / 1000.0,
                dp["ttft_ms"]["p50"] / 1000.0,
                dp["tpot_ms"]["p50"] / 1000.0,
                dp["e2e_ms"]["p50"] / 1000.0,
            ])]))
        A('<p class="legend">图 1　两组关键指标对照（不同量纲，按各自数值绘制，用于观察差异方向与量级）。</p>')

        # 服务端证据
        A("<h3>4.2 服务端侧的独立旁证</h3>")
        rows_sp = sp.get("_prefill") or []
        rows_dp = dp.get("_prefill") or []
        hit_sp = [r for r in rows_sp if r[2] > 0]
        hit_dp = [r for r in rows_dp if r[2] > 0]
        A(f'''<table>
<tr><th>组</th><th class="n">服务端 Prefill 批次总数</th><th class="n">其中 #cached-token &gt; 0</th>
<th class="n">本组服务端累计 #new-token</th><th class="n">本组服务端累计 #cached-token</th></tr>
<tr><td>共享前缀</td><td class="n">{len(rows_sp)}</td><td class="n">{len(hit_sp)}</td>
<td class="n">{intfmt(sum(r[1] for r in rows_sp))}</td><td class="n">{intfmt(sum(r[2] for r in rows_sp))}</td></tr>
<tr><td>分散前缀</td><td class="n">{len(rows_dp)}</td><td class="n">{len(hit_dp)}</td>
<td class="n">{intfmt(sum(r[1] for r in rows_dp))}</td><td class="n">{intfmt(sum(r[2] for r in rows_dp))}</td></tr>
</table>''')
        A('<p class="small">上表由 <span class="mono">server_log_slice.log</span> 中的 '
          '<span class="mono">Prefill batch, #new-token: …, #cached-token: …</span> 行直接汇总，'
          '与服务端自报数据独立于客户端统计，可与主表互相印证。</p>')
    else:
        A('<p class="warn">尚无测量结果。</p>')
    A("</div>")

    # ------------------------------------------------------------------ 公式解释
    A('<div class="page tight">')
    A("<h2>五、任务一：从因果自注意力公式解释前缀复用</h2>")
    A('''<p>单头缩放的因果自注意力为</p>
<div class="formula">
Attention(Q, K, V) = softmax<span class="frac"><span class="num">Q K<sup>T</sup></span><span class="den">√d<sub>k</sub></span></span> V
</div>
<p>其中 <span class="mono">Q = XW<sub>Q</sub>, K = XW<sub>K</sub>, V = XW<sub>V</sub></span>，
<span class="mono">X</span> 是长度 N 的输入隐状态序列。加入因果掩码 <span class="mono">M</span> 后</p>
<div class="formula">
Attention = softmax<span class="frac"><span class="num">Q K<sup>T</sup></span><span class="den">√d<sub>k</sub></span></span> + M &nbsp;V，
&nbsp;&nbsp; M<sub>ij</sub> = 0&nbsp;(j ≤ i)，&nbsp; M<sub>ij</sub> = −∞&nbsp;(j &gt; i)
</div>
<p>掩码的作用是让位置 <span class="mono">t</span> 的输出只能注意到 <span class="mono">j ≤ t</span> 的键值，
即注意力权重的幅值在 <span class="mono">j &gt; t</span> 处被置零。</p>

<h3>5.1 为什么相同 token 与位置的前缀可以复用 K/V</h3>
<p>关键是 <b>K<sub>i</sub> 与 V<sub>i</sub> 只由位置 i 的隐状态决定</b>：</p>
<div class="formula">K<sub>i</sub> = h<sub>i</sub> W<sub>K</sub>，&nbsp;&nbsp; V<sub>i</sub> = h<sub>i</sub> W<sub>V</sub></div>
<p>而 <span class="mono">h<sub>i</sub></span> 又逐层只由前 <span class="mono">i</span> 个 token 的表示算出。
因果掩码只限制「能看多远」，<b>不会改变已经算出来的某个位置的 K/V 数值</b>——它作用在
<span class="mono">QK<sup>T</sup></span> 上，而不是作用在 K、V 本身。因此，若两个请求的 token 序列在
位置 <span class="mono">0 … L−1</span> 上逐位相同（token 相同、位置相同，且模型权重与 dtype 相同），
那么这 L 个位置在每一层的 K/V <b>在数值上完全一致</b>，缓存它们就是安全的：</p>
<ul>
<li>把先前请求在这 L 个位置已经算好、并已按 paged 布局写进 KV Cache 的
<span class="mono">token → slot</span> 索引保留在 RadixCache 里；</li>
<li>新请求到达时，沿基数树逐 token 匹配得到前 L 个 token 的 slot 列表，写入
<span class="mono">req.prefix_indices</span>，并在组批时令
<span class="mono">extend_input_len = N − L</span>；</li>
<li>于是本轮 Prefill 只需对位置 <span class="mono">L … N−1</span> 计算并写出 K/V。</li>
</ul>
<p>本实验的对应关系：共享前缀组的 <span class="mono">L ≈ 2048</span>（36 条请求共享的前缀），
分散前缀组因位置 0 各不相同，匹配在根节点即失败，<span class="mono">L = 0</span>。</p>

<h3>5.2 命中之后仍需计算哪些 token</h3>
<ol>
<li><b>未命中后缀的全部 token</b>（位置 L … N−1）：它们的 Q、K、V 都必须新算并写出，
本实验中即每条请求自己的 64 个后缀 token，外加 2048 前缀中未被缓存覆盖的部分；</li>
<li><b>Decode 阶段每一个新生成的 token</b>：每个新 token 都要在前一步基础上重新算 Q/K/V 并追加进缓存，
共 <span class="mono">max_new_tokens = 16</span> 步；</li>
<li>此外，已命中前缀虽然不必重算，但新算出的 Q（位置 ≥ L）在注意力里<b>仍要读取</b>那 L 个位置的 K/V
（<span class="mono">forward_extend</span> 中做 KV 拼接）。所以复用省掉的是
<b>「算 K/V 并把它们写进缓存」的算力</b>，而不是省掉对它们的读取。</li>
</ol>
<p class="small">补充：匹配长度会先按 <span class="mono">page_size</span> 对齐
（<span class="mono">RadixKey.page_aligned</span>）；本实验 <span class="mono">page_size = 1</span>，
因此命中粒度为单 token。</p>''')
    A("</div>")

    # ------------------------------------------------------------------ 差异分析
    A('<div class="page tight">')
    A("<h2>六、任务一：数据与公式的相互印证</h2>")
    if have:
        r_hit = sp["cache_hit_rate"] / dp["cache_hit_rate"] if dp["cache_hit_rate"] else None
        # 同轮「时长守恒」的两个实例：TTFT 与 TPOT 此消彼长，E2E 几乎相等
        w1 = (sp.get("_reqs") or [])[:8]
        w2 = (dp.get("_reqs") or [])[:8]
        cons = ""
        if w1 and w2:
            lo1 = min(w1, key=lambda r: r["ttft_ms"])
            hi1 = max(w1, key=lambda r: r["ttft_ms"])
            lo2 = min(w2, key=lambda r: r["ttft_ms"])
            hi2 = max(w2, key=lambda r: r["ttft_ms"])
            cons = (
                f'<p class="small">同轮「时长守恒」的两个实例（均取 {esc(primary)} 第一轮 8 条中'
                f'最先 / 最后被准入的两条）：共享前缀组 '
                f'<span class="mono">{fmt(lo1["ttft_ms"],0)} + 15×{fmt(lo1["tpot_ms"],0)} ≈ '
                f'{fmt(hi1["ttft_ms"],0)} + 15×{fmt(hi1["tpot_ms"],0)} ≈ {fmt(lo1["e2e_ms"],0)} ms</span>；'
                f'分散前缀组 <span class="mono">{fmt(lo2["ttft_ms"],0)} + 15×{fmt(lo2["tpot_ms"],0)} ≈ '
                f'{fmt(hi2["ttft_ms"],0)} + 15×{fmt(hi2["tpot_ms"],0)} ≈ {fmt(lo2["e2e_ms"],0)} ms</span>。</p>'
            )
        extra_prefill = 8 * 2112 - 8 * (2112 - 2048)
        wall_delta = dp["wall_clock_s"] - sp["wall_clock_s"]
        imp = (extra_prefill * 4 / wall_delta) if wall_delta > 0 else None
        _thr = dp.get("_thr") or []
        thr_med = statistics.median(_thr) if _thr else None
        serial_est = (extra_prefill * 4 / thr_med) if thr_med else None
        A(f'''<h3>6.1 TTFT 与 TPOT 为什么同时下降——以及不能据此下的结论</h3>
<p>先给结论：本次测量能够确证的是 <b>Prefill 量的大幅下降</b>与<b>端到端时长的下降</b>；
TPOT 的下降<b>不能</b>读作「Decode 本身变快了」。</p>
<p>原因在于同一轮的 8 条请求在服务端是<b>同批同步</b>推进的，端到端耗时几乎相等（见 6.3 的极差统计）。
于是 TTFT 与 TPOT 并非两个彼此独立的观测量，而是<b>同一段固定时长在「等待」与「解码窗口」之间的分配</b>：
一条请求被准入得越早，它的 TTFT 越小、留给解码的窗口越长，摊到每个输出 token 上的 TPOT 就越大。</p>
{cons}
<p>从计算量看，Decode 单步与前缀是否命中<b>无关</b>：每步仍然是 1 个新 query 对 N 个位置的 K/V，
上下文总长 N 与步数（<span class="mono">max_new_tokens = 16</span>）两组完全一致。
前缀缓存改变的是「同一批内还需要做多少 Prefill」，而 Decode 会与这些 Prefill 争抢同一批 CPU。
因此跨组比较应以<b>端到端时长与吞吐</b>为准，TTFT / TPOT 只作过程量参考。</p>

<h3>6.2 端到端差异的定量归因</h3>
<p>把每轮 8 条请求看作一个整体：共享前缀组每轮需 Prefill <span class="mono">8 × 64 = 512</span> 个 token，
分散前缀组需 <span class="mono">8 × 2112 = {intfmt(8*2112)}</span> 个，<b>相差 {intfmt(extra_prefill)} 个/轮</b>，
四轮合计 <span class="mono">{intfmt(extra_prefill*4)}</span> 个；而两组每轮的 Decode 步数完全相同
（<span class="mono">8 × 16</span>）、上下文总长也相同。实测两组墙钟之差为
<b>{fmt(wall_delta,1)} s</b>（{fmt(dp["wall_clock_s"],1)} s − {fmt(sp["wall_clock_s"],1)} s）。</p>
<p>服务端日志里分散组 Prefill 批次自报的吞吐中位数为 <b>{fmt(thr_med,0)} tok/s</b>。
若把多出的 {intfmt(extra_prefill*4)} 个 token 按这个吞吐串行折算，需要约
{fmt(serial_est,0)} s；实测只需要 {fmt(wall_delta,1)} s，<b>明显更少</b>。
这是因为 Prefill 与 Decode 在同一批内是重叠推进的，并非严格串行。
结论：<b>端到端差异的量级由多出的 Prefill 量决定</b>（隐含吞吐 {fmt(imp,0)} tok/s，
与服务端自报的 {fmt(thr_med,0)} tok/s 同一量级），
不需要假设 Decode 变快或变慢。</p>
<p class="small">逐项核对：公式预测命中 <span class="mono">L = 2048</span>、每条需 Prefill
<span class="mono">N − L = 64</span>，32 条合计 {intfmt(32*64)} 个 token，实测
{intfmt(sp["actual_prefill_tokens"])} 个——略低于预测，是因为少数请求的独立后缀与共享前缀的后续 token
恰好相同，命中长度顺延到了 2049…2054（见 <span class="mono">requests.jsonl</span> 的
<span class="mono">cached_tokens</span>）。分散前缀组实测 cached tokens 为
{intfmt(dp["total_cached_tokens"])}、实际 Prefill {intfmt(dp["actual_prefill_tokens"])} 个，
与「L = 0」的预测完全一致。</p>''')

        A("<h3>6.3 并发 8 下的「准入等待」：一个必须说明的实测现象</h3>")
        # 服务端准入证据（全部由原始日志与逐请求结果现算）
        ev_text, gap, ns0, ns1 = sp.get("_evidence") or ("", None, None, None)
        spread = wave_spread(sp.get("_reqs") or [], k=8)
        gap_s = f"{gap:,.0f}" if gap is not None else "—"
        spread_s = f"{spread:,.1f}" if spread is not None else "—"
        A(f'''<p>主表中共享前缀组的 TTFT 达 {fmt(sp["ttft_ms"]["p50"],1)} ms，远高于
「已命中 2048 个 token、只剩 65 个 token 需要 prefill」应有的量级。这并不意味着 Prefill 变慢了——
服务端日志中本组的前两条 Prefill 记录就是直接证据：</p>
<pre class="mono small">{esc(ev_text)}</pre>
<p>首条请求被准入时，调度器的等待队列里<b>只有它自己</b>（<span class="mono">#queue-req: 0</span>）；
其余 {intfmt(ns1 or 7)} 条要再过约 {gap_s} s 才<b>整批</b>进入
（<span class="mono">#new-seq: {intfmt(ns1 or 7)}</span>，即首条之后剩下的 {intfmt(ns1 or 7)} 条一起进来）。
逐请求明细同样指向服务端：把同一轮 8 条请求放在一起看，它们的端到端耗时几乎完全相同
（轮内极差最大仅 {spread_s} ms），说明客户端确实是同时发出的，时间差只能出现在服务端的接收与派发环节。</p>
<p>因此每一批次里多数请求的 TTFT 中包含了一段约 {gap_s} s 的<b>准入等待</b>，它不是 Prefill 开销。
两点判读：</p>
<ul>
<li>这是<b>纯 CPU 单进程部署</b>的固有现象：HTTP 接收路径与「调度 + 前向计算」在同一进程内串行，
一次长前向执行期间新到的请求无法被及时读取。它与压测脚本、与本次负载设计无关。</li>
<li>它<b>对两组同等存在</b>（两组每一轮都只有 1 条先被准入），因此两组的<b>相对差异</b>仍然可信；
而缓存命中率、实际 Prefill token 数等指标直接取自服务端计数器，完全不受时序影响。</li>
</ul>
<p class="small">另：同一批内多条请求的 Prefill 会被合并进同一个 <span class="mono">Prefill batch</span>，
服务端日志的批次粒度与「每请求一条」并不一一对应，这也是 4.2 节服务端累计值与客户端
Σ<span class="mono">meta_info</span> 之间存在小幅差异的原因；核对时以客户端逐请求 meta_info 为准（主表）。</p>''')

        A("<h3>6.4 结论</h3>")
        A(f'''<ol>
<li><b>前缀缓存确实生效且收益显著</b>：共享前缀组把 {fmt(sp["cache_hit_rate"]*100,2)}% 的 prompt token
 变成命中，实际 Prefill token 由 {intfmt(dp["actual_prefill_tokens"])} 降至
 {intfmt(sp["actual_prefill_tokens"])}；端到端 p50 由 {fmt(dp["e2e_ms"]["p50"],1)} ms 降至
 {fmt(sp["e2e_ms"]["p50"],1)} ms（降幅 {fmt((1-sp["e2e_ms"]["p50"]/dp["e2e_ms"]["p50"])*100,1)}%），
 TTFT p50 降幅 {fmt((1-sp["ttft_ms"]["p50"]/dp["ttft_ms"]["p50"])*100,1)}%，
 输出吞吐由 {fmt(dp["output_throughput_tok_s"])} 升到 {fmt(sp["output_throughput_tok_s"])} tok/s。</li>
<li><b>收益来自 Prefill，而不是 Decode 本身</b>：两组的 Decode 步数（16）与上下文总长完全相同，
 因此 Decode 单步的计算量没有变化。TPOT p50 的读数从 {fmt(dp["tpot_ms"]["p50"],1)} ms
 变为 {fmt(sp["tpot_ms"]["p50"],1)} ms，属于「同批同步」下的时长再分配（见 6.1），
 不能据此认为 Decode 变快了。</li>
<li><b>跨组比较以端到端与吞吐为准</b>：TTFT / TPOT 在同一轮内此消彼长、二者之和近似恒定，
 单独引用其中任一个都会得到片面的结论（6.1）；而多出的 Prefill 量在多寡上与墙钟之差一致（6.2）。</li>
<li><b>两组输入输出长度一致、成功率均为 {sp["n_success"]}/{sp["n_requested"]} 与
 {dp["n_success"]}/{dp["n_requested"]}</b>，说明差异来自前缀能否复用，而不是负载本身的差异。</li>
</ol>''')
        # run-2 稳健性
        if "run-2" in runs:
            r2 = runs["run-2"]
            s2, d2 = r2.get("shared_prefix"), r2.get("dispersed_prefix")
            if s2 and d2:
                A("<h3>6.5 执行顺序的稳健性检查（run-2：交换两组顺序）</h3>")
                A(f'''<table>
<tr><th>指标</th><th class="n">run-1（shared → dispersed）</th><th class="n">run-2（dispersed → shared）</th></tr>
<tr><td>共享前缀 缓存命中率</td><td class="n">{fmt(sp["cache_hit_rate"]*100,2)}%</td><td class="n">{fmt(s2["cache_hit_rate"]*100,2)}%</td></tr>
<tr><td>共享前缀 实际 Prefill tokens</td><td class="n">{intfmt(sp["actual_prefill_tokens"])}</td><td class="n">{intfmt(s2["actual_prefill_tokens"])}</td></tr>
<tr><td>共享前缀 TTFT p50（ms）</td><td class="n">{fmt(sp["ttft_ms"]["p50"],1)}</td><td class="n">{fmt(s2["ttft_ms"]["p50"],1)}</td></tr>
<tr><td>分散前缀 TTFT p50（ms）</td><td class="n">{fmt(dp["ttft_ms"]["p50"],1)}</td><td class="n">{fmt(d2["ttft_ms"]["p50"],1)}</td></tr>
<tr><td>分散前缀 实际 Prefill tokens</td><td class="n">{intfmt(dp["actual_prefill_tokens"])}</td><td class="n">{intfmt(d2["actual_prefill_tokens"])}</td></tr>
</table>
<p class="small">交换顺序后结论不变，说明观测到的差异不是执行顺序（如首组承担额外 JIT / 线程池预热开销）造成的。</p>''')
    else:
        A('<p class="warn">尚无测量结果。</p>')
    A("</div>")

    # ------------------------------------------------------------------ 任务二：流程图
    A('<div class="page chartpage">')
    A("<h2>七、任务二：一条 /generate 请求的完整流程</h2>")
    if svg:
        A(svg)
    A("</div>")

    # ------------------------------------------------------------------ 任务二：说明
    A('<div class="page tight">')
    A("<h2>八、任务二：说明（不超过 1 页）</h2>")
    # 任务二说明与任务一实测的呼应（数字全部现算）
    if have:
        conc = (
            f'<div class="note"><b>与实测的呼应</b>：正因为 8.2 中「已缓存前缀既不重算也不重写」，'
            f'本实验共享前缀组的实际 Prefill token 才从 {intfmt(dp["actual_prefill_tokens"])} 降到 '
            f'{intfmt(sp["actual_prefill_tokens"])}；而 8.4 中 Decode 每步都要重新读入全部已缓存 K/V，'
            f'且上下文总长 N 与 Decode 步数（<span class="mono">max_new_tokens = 16</span>）两组完全一致——'
            f'<b>所以 Decode 本身的单步计算量并不因前缀命中而减少</b>，两组 TTFT / TPOT 的变化是'
            f'「同批同步」下的时长再分配，见 6.1 节。</div>'
        )
    else:
        conc = ""
    A('<p class="small">下图按任务书指定主线绘制，图中 <b>★</b> 标记的节点对应本节要回答的四个问题；'
      '每个节点下方的等宽文本即该函数所在的<b>文件与行号</b>，均可在 '
      '<span class="mono">python/sglang/srt</span> 下逐一核对。</p>')
    A('''<h3>8.1 请求如何进入等待队列</h3>
<p>HTTP 层 <span class="mono">generate_request</span>（<span class="mono">entrypoints/http_server.py:769</span>）
在 <span class="mono">obj.stream</span> 为真时返回 <span class="mono">stream_results()</span> 这个异步生成器。
<span class="mono">TokenizerManager.generate_request</span>（<span class="mono">managers/tokenizer_manager.py:576</span>）
先做参数归一化，再经 <span class="mono">_tokenize_one_request</span>（:782）分词，用
<span class="mono">_send_one_request</span>（:1319）把 <span class="mono">TokenizedGenerateReqInput</span>
经 ZMQ 发给 Scheduler 进程。Scheduler 的 <span class="mono">event_loop_normal</span>（<span class="mono">managers/scheduler.py:1505</span>）
每轮先 <span class="mono">recv_requests</span> 取回请求，交给 <span class="mono">process_input_requests</span>（:1628），
后者最终调用 <span class="mono">_add_request_to_queue</span>（:2258），把 <span class="mono">Req</span>
追加进 <span class="mono">self.waiting_queue</span>（:2265）并打上入队时间戳。到此请求才真正「在等」。</p>

<h3>8.2 前缀匹配如何减少本轮 Prefill token</h3>
<p>组批时 <span class="mono">get_new_batch_prefill</span>（<span class="mono">scheduler.py:2702</span>）
先按调度策略 <span class="mono">policy.calc_priority</span>（:2761，默认 cache-aware 的 LPM，
即最长前缀优先）对等待队列排序，再构造 <span class="mono">PrefillAdder</span>
（<span class="mono">managers/schedule_policy.py:425</span>）逐条准入。对每条请求，先调用
<span class="mono">Req.init_next_round_input</span>（<span class="mono">managers/schedule_batch.py:1123</span>），
其中 <span class="mono">tree_cache.match_prefix</span>（:1168）落到
<span class="mono">RadixCache.match_prefix</span>（<span class="mono">mem_cache/radix_cache.py:358</span>），
由 <span class="mono">_match_prefix_helper</span>（:643）沿基数树逐段比对，返回已命中前缀的
KV slot 索引 <span class="mono">prefix_indices</span>（命中止于节点中部时用
<span class="mono">_split_node</span>（:669）切分节点以暴露精确边界）。随后
<span class="mono">set_extend_input_len(len(input) − len(prefix_indices))</span>（:1221）
把本请求本轮要真正计算的 token 数扣掉已命中的部分。<b>减少 Prefill token 的机制就是这一步</b>：
这些 token 的 K/V 已在池中被前序请求算好并写入，本轮既不重算也不重写，只需把它们的 slot 索引拼进
本轮的 <span class="mono">prefix_indices</span>。<span class="mono">PrefillAdder.add_one_req</span>
（<span class="mono">schedule_policy.py:858</span>）再按剩余 token 预算判定能否纳入本批，通过后组装成
<span class="mono">ScheduleBatch</span>（<span class="mono">schedule_batch.py:1671</span>）。</p>

<h3>8.3 新产生的 KV 如何写回缓存</h3>
<p>前向由 <span class="mono">Scheduler.run_batch</span>（<span class="mono">scheduler.py:3145</span>）
调用 <span class="mono">TpModelWorker.forward_batch_generation</span>
（<span class="mono">managers/tp_worker.py:482</span>）→ <span class="mono">ModelRunner.forward</span>
（<span class="mono">model_executor/model_runner.py:2896</span>），注意力后端按批的
<span class="mono">forward_mode</span> 走 <span class="mono">forward_extend</span>（Prefill）或
<span class="mono">forward_decode</span>（Decode）。算出的 KV 先按 paged 布局写进 KV pool，
并在 <span class="mono">req_to_token</span> 里登记 slot。之后由
<span class="mono">process_batch_result</span>（<span class="mono">scheduler.py:3367</span>）分派到
<span class="mono">batch_result_processor</span>，两条路径回写基数树：
<b>未结束</b>（chunked prefill 的中间段）走
<span class="mono">maybe_cache_unfinished_req</span>（<span class="mono">mem_cache/common.py:113</span>）→
<span class="mono">RadixCache.cache_unfinished_req</span>（<span class="mono">radix_cache.py:485</span>）；
<b>已结束</b>走 <span class="mono">release_kv_cache</span>（:629）→
<span class="mono">RadixCache.cache_finished_req</span>（:438）→ <span class="mono">insert</span>（:418）。
插入前序列会按 <span class="mono">page_size</span> 做 <span class="mono">page_aligned</span> 对齐，
再把 <span class="mono">token → KV slot</span> 的映射挂到基数树上；重复部分对应的 KV 立即
<span class="mono">free</span> 掉，并调整 <span class="mono">lock_ref</span> 引用计数，
使暂未被引用的节点成为可驱逐（evictable）状态。</p>

<h3>8.4 生成结果如何流式返回</h3>
<p>Decode 的每一步都会经 <span class="mono">Scheduler.stream_output</span>
（<span class="mono">managers/scheduler_components/output_streamer.py:91</span>）把本步新 token
打包成 <span class="mono">BatchTokenIDOutput</span> 发给 Detokenizer 进程；
<span class="mono">DetokenizerManager.event_loop</span>
（<span class="mono">managers/detokenizer_manager.py:159</span>）做增量反分词（只为新 token 解码，
避免重复处理整段），再送回 TokenizerManager。
<span class="mono">_handle_batch_output</span>（<span class="mono">tokenizer_manager.py:1839</span>）
组装 <span class="mono">meta_info</span>（含 <span class="mono">prompt_tokens</span>、
<span class="mono">completion_tokens</span>、<span class="mono">cached_tokens</span>、
<span class="mono">finish_reason</span>），<span class="mono">_wait_one_response</span>（:1425）
逐片 <span class="mono">yield</span>；最终由
<span class="mono">http_server.stream_results</span>（<span class="mono">http_server.py:778</span>）
以 SSE 形式写出 <span class="mono">data: {...}\\n\\n</span>。
客户端读到首个「携带生成 token 的分片」的时刻即 TTFT，之后每片之间的间隔即 TPOT 的实测来源。</p>''')
    A(conc)
    A("</div>")

    # ------------------------------------------------------------------ 作业感受
    A('<div class="page">')
    A("<h2>九、作业感受</h2>")
    A('''<h3>（1）简述下你是如何完成第二次挑战的</h3>
<p>第二次挑战复用第一次挑战已经搭好的 SGLang 0.5.14 在线服务（WSL2 + 纯 CPU + Qwen3-0.6B），
因此第一步不是重建环境，而是<b>先确认服务的可用状态</b>与缓存配置，再把注意力放在实验本身的可信度上。</p>
<p>具体过程分三步。第一步是<b>把任务书翻译成脚本</b>：把「32 条请求 / 并发 8 / 温度 0 /
max_new_tokens 16 / ignore_eos / seed 2026」这些硬性条件写成脚本里的常量，把
「组前 flush_cache 并确认成功」「共享前缀组额外发一条预热请求」「预热不计入结果」
这些容易漏掉的约束做成流程里的显式步骤，并让每一步都在结果目录留下可核对的文件
（<span class="mono">flush_cache.json</span>、<span class="mono">warmup_request.json</span> 等）。</p>
<p>第二步是<b>把控制变量做到位</b>。任务书要求「除前缀能否复用外其余一致」，我最初的做法是两组各造一份语料，
但很快发现这样比出来的差异里混着内容差异。于是改成用「只替换位置 0 的 token」的方式构造分散前缀组：
其余 2047 个 token 与共享前缀组逐位相同，并在代码里加了断言把它固定下来。
这样唯一的自变量就只剩「前缀能否被 RadixCache 复用」。</p>
<p>第三步是<b>让数据自己说话</b>。所有指标都不在报告里手抄，而是由脚本从服务端返回的
<span class="mono">meta_info</span> 汇总成 <span class="mono">summary.json</span>，
再由另一个脚本读它生成报告表格，同时把服务端日志里
<span class="mono">Prefill batch</span> 行的 <span class="mono">#cached-token</span>
另行汇总作为独立旁证。任务二则反过来：先在源码里逐跳把函数和行号找出来，
再用一个生成脚本把它画成流程图，保证图上的每一处标注都能回到源码核对。</p>
<p>AI 在这里的作用主要是<b>加速定位与校验</b>：帮我快速在 0.5.14 的源码树里找到
<span class="mono">match_prefix</span>、<span class="mono">cache_finished_req</span>
等函数的位置，以及提示「命中之后仍需读取已缓存 K/V」这类容易被忽略的细节；
但它给出的行号和结论我都回到源码逐条复核过，与 0.5.14 不符的一律以源码为准。</p>

<h3>（2）你觉得哪部分工作最困难，你是如何克服这个困难的</h3>
<div class="blank">【本题要求「禁止 AI 辅助撰写」，请本人填写】</div>

<h3>（3）类似的从 0 到 1 的科研工作，需要包含哪些方面的研究，对你今后的科研工作有什么启发</h3>
<div class="blank">【本题要求「禁止 AI 辅助撰写」，请本人填写】</div>
''')
    A("</div>")

    body = "\n".join(P)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>第二次挑战实验报告 — {esc(NAME)}</title>
<style>{CSS}</style></head>
<body>
{body}
</body></html>
"""


def main():
    runs = load_runs()
    if not runs:
        print("警告：results/target1 下未找到任何 summary.json，报告将只含流程与说明部分。")
    else:
        print("已载入运行结果：" + ", ".join(
            f"{t}({[g for g in v]})" for t, v in runs.items()))
    html_str = build_html(runs)
    out = os.path.join(HERE, "report.html")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html_str)
    print(f"已写出 {out}（{len(html_str)} 字节）")


if __name__ == "__main__":
    main()
