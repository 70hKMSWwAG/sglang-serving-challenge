#!/usr/bin/env python3
"""生成 HW2 的 作业感受.pdf 与 AI 使用说明情况（第二次挑战）.pdf。"""

import subprocess
from pathlib import Path

HW2 = Path("/workspace/HW2")
BUILD = HW2 / "build"
BUILD.mkdir(parents=True, exist_ok=True)

CSS = """
@page { size: A4 portrait; margin: 15mm 14mm; }
body { font-family: "Noto Sans CJK SC", sans-serif; font-size: 10.4pt; line-height: 1.62; color: #1a1a1a; }
h1 { font-size: 15.5pt; margin: 0 0 1.5mm; }
h2 { font-size: 11.5pt; margin: 4mm 0 1.8mm; padding-left: 2.5mm; border-left: 3.5px solid #4285f4; }
p { margin: 1.6mm 0; text-align: justify; }
code { font-family: "Noto Sans Mono CJK SC", monospace; font-size: 8.9pt; background: #f4f5f7; padding: 0.3mm 1mm; border-radius: 2px; }
ul, ol { margin: 1.2mm 0 1.2mm 5.5mm; padding: 0; }
li { margin: 1mm 0; }
.meta { color: #555; font-size: 9pt; margin-bottom: 3mm; }
table { width: 100%; border-collapse: collapse; font-size: 9pt; margin: 2mm 0; }
th, td { border: 0.6px solid #b9bec7; padding: 1.2mm 1.6mm; text-align: left; vertical-align: top; }
th { background: #eef1f5; }
.todo { border: 1.2px dashed #d97706; background: #fffbeb; padding: 4mm 4mm; margin: 2.5mm 0;
        border-radius: 3px; color: #7c4a03; font-size: 9.8pt; }
.todo b { color: #92400e; }
.small { font-size: 9pt; color: #444; }
"""


def write_pdf(name, body):
    html_path = BUILD / f"{name}.html"
    html_path.write_text(
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{CSS}</style></head>'
        f"<body>{body}</body></html>", encoding="utf-8")
    out = HW2 / f"{name}.pdf"
    subprocess.run([
        "chromium", "--headless", "--disable-gpu", "--no-sandbox",
        "--no-pdf-header-footer", f"--print-to-pdf={out}", f"file://{html_path}",
    ], check=True, capture_output=True, timeout=300)
    print("wrote", out)


FEELINGS = """
<h1>作业感受（第二次挑战）</h1>
<div class="meta">HW2 第五部分</div>

<h2>（1）简述你是如何完成第二次挑战的</h2>
<p>这一次的关键词是"对照"。我先按题目要求把实验口径定死：两组各 32 条请求、并发 8、输入固定 1024 token
（共享前缀 896 + 各自后缀 128）、<code>max_new_tokens=16</code>、<code>temperature=0</code>、
<code>ignore_eos=true</code>、<code>sampling_seed=2026</code>，除"前缀能否复用"外全部保持一致，
然后用脚本把流程固化下来：服务预热 → 等待空闲 → <code>POST /flush_cache</code> 并校验返回 →
共享前缀组额外发一条预热请求 → 并发回放。采集指标时我特意区分了客户端计时（TTFT/TPOT/E2E）与服务端
<code>meta_info</code>（<code>cached_tokens</code>），这样"命中了多少"与"快了多少"能互相对照。</p>
<p>中途踩了三个坑，都是靠"让脚本自己报错"发现的：一是把 <code>/flush_cache</code> 的返回判错，
脚本一直认为服务不空闲；二是第一版"分散前缀"其实生成了相同文本，分散组命中率高达 74.9%，
我加了"最长公共前缀自检"才暴露出来，改成分散语料后降到 0.56%；三是容器内存限额只有 8 GB，
KV 池开大了会被 OOM 杀掉。修完后两组各跑 3 轮，结果非常稳定（命中率三轮完全一致），
才开始动笔写报告。AI 在其中主要扮演"报错解释器 + 源码导航 + 文档骨架"的角色，
而实验设计、指标口径与结论判断都是我自己定的。</p>

<h2>（2）你觉得哪部分工作最困难，你是如何克服这个困难的</h2>
<div class="todo">
<b>【本小题作业要求禁止 AI 辅助撰写，以下为空白模板，请由本人手写填写后替换】</b><br><br>
最困难的部分：<br>
________________________________________________________________<br>
________________________________________________________________<br><br>
我是这样克服的：<br>
________________________________________________________________<br>
________________________________________________________________<br>
</div>

<h2>（3）你觉得类似的从 0 到 1 的科研工作，需要包含哪些方面的研究，对你今后的科研工作有什么启发</h2>
<div class="todo">
<b>【本小题作业要求禁止 AI 辅助撰写，以下为空白模板，请由本人手写填写后替换】</b><br><br>
需要包含的研究方面：<br>
________________________________________________________________<br>
________________________________________________________________<br><br>
对今后科研的启发：<br>
________________________________________________________________<br>
________________________________________________________________<br>
</div>
"""

AI_USAGE = """
<h1>AI 使用说明情况（第二次挑战）</h1>
<div class="meta">HW2 第四部分</div>

<h2>1. 使用的 AI 模型</h2>
<p>CodeBuddy 智能编码助手（内置大模型，具备沙箱终端、文件读写与联网检索能力）。</p>

<h2>2. 使用的提示词（真实摘录）</h2>
<table>
<tr><th style="width:20%">环节</th><th>提示词 / 指令</th><th style="width:32%">AI 的实际作用</th></tr>
<tr><td>实验脚本</td><td>"帮我写基准脚本：32 条请求、并发 8，共享前缀组 vs 分散前缀组，/generate 提交 input_ids 并流式，要预热、flush_cache、记录 TTFT/TPOT/命中率"</td>
<td>给出 <code>run_benchmark.py</code> 的异步并发骨架与指标计算方式</td></tr>
<tr><td>接口语义</td><td>"flush_cache 一直返回 not idle，帮我查服务端实现"</td>
<td>定位到 <code>http_server.py:841</code>：成功固定返回 200 + <code>Cache flushed.</code>，修正判定逻辑</td></tr>
<tr><td>源码主线</td><td>"沿 TokenizerManager.generate_request → event_loop_normal → get_new_batch_prefill → match_prefix → worker → cache_finished_req → streaming 帮我定位 v0.5.14 的函数与行号"</td>
<td>给出函数清单与文件:行号，我再逐段精读核对（如 <code>schedule_batch.py:1221</code> 的 <code>set_extend_input_len</code>）</td></tr>
<tr><td>理论与成文</td><td>"从因果自注意力公式出发解释前缀复用，并说明 TTFT 与 TPOT 为何变化不同"</td>
<td>协助把公式与机制组织成文，数据仍取自实测结果</td></tr>
<tr><td>可视化</td><td>"把主流程画成一张图，标出关键函数所在文件"</td>
<td>生成 SVG 流程图，我再调整布局与配色</td></tr>
</table>

<h2>3. AI 如何帮助我学习</h2>
<ul>
<li><b>源码导航：</b>v0.5.14 的调度/缓存模块很大，AI 先给出函数级地图，我再精读关键分支，
把"机制—代码—指标"三者对上号。</li>
<li><b>把直觉变成可检验的假设：</b>"前缀复用只优化 Prefill、不影响 Decode"这一判断，
在 AI 协助下变成了两组对照实验，并被 TPOT −1.1% 的数据验证。</li>
<li><b>加速文档与绘图</b>，让我把时间集中在实验设计与结果核对上。</li>
</ul>

<h2>4. 是否被误导（真实案例）</h2>
<ul>
<li><b>接口语义误判：</b>AI 依据单次输出认为 <code>/flush_cache</code> 成功时不含括号提示句，
导致脚本误判"服务永不空闲"；对照源码后修正。<b>教训：以源码为准。</b></li>
<li><b>负载构造假设错误：</b>AI 生成的"分散前缀"用循环拼接语料，实际各组前缀相同
（分散组命中率 74.9%），加入公共前缀自检后才发现并修复。<b>教训：负载要断言其统计性质，而不是只看能否跑通。</b></li>
<li><b>环境假设偏差：</b>AI 一开始按 GPU 环境的默认内存参数给命令，而容器限额只有 8 GB，
scheduler 被 OOM kill；读 cgroup 指标后改为显式压小 KV 池。<b>教训：先确认资源约束，再谈参数。</b></li>
</ul>
<p class="small">结论：AI 在"检索、排错、成文"环节帮助很大，但它的经验性假设必须经实测校验。
本报告中所有数字均来自脚本真实运行产生的 <code>results/</code> 原始文件，可逐条回溯。</p>
"""


def main():
    write_pdf("作业感受", FEELINGS)
    write_pdf("AI 使用说明情况（第二次挑战）", AI_USAGE)


if __name__ == "__main__":
    main()
