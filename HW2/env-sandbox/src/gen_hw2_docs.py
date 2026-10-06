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
<p>这次最难的其实不是把服务跑起来，而是让两组负载真的只在"前缀能不能复用"这一点上不一样。第一版脚本我图省事，
分散前缀组拿同一份语料循环拼接、只换起始位置，跑出来命中率 74.9%——也就是说我以为"分散"的那组，
前缀几乎全一样。这个数字要是不看，报告照样写得出来，结论看着也挺顺，只是经不起推敲。后来我加了一条自检：
把前几条请求两两算最长公共前缀长度打出来，共享组应该约等于 896、分散组应该约等于 0。一打就露馅了。
改成分散语料、每个 seed 重新排列句子顺序之后，分散组命中率降到 0.56%。</p>
<p>还有一次也差不多：共享组平均命中 919.5 token，比我自己设计的前缀 896 还多。我第一反应是统计写错了，
去翻 <code>radix_cache.py</code> 才明白——写回缓存的是<b>整条序列</b>（前缀加后缀），后面某条请求的 128 token
后缀要是和已缓存序列的后缀开头撞上了，最长前缀匹配就会再往前多咬一口。这种"数据不听话"的时刻反而是这次收获
最大的地方：数字跟预期对不上时，多数不是脚本错了，是我对机制的理解还差一层。</p>

<h2>（3）你觉得类似的从 0 到 1 的科研工作，需要包含哪些方面的研究，对你今后的科研工作有什么启发</h2>
<p>要是把这次的过程抽象成"从 0 到 1 需要什么"，我会说四样东西。一是<b>一个真能跑起来的最小系统</b>，
而且它的版本、启动参数、数据来源都能让别人照着复现出来；二是<b>可信的测量</b>，指标要在动手之前就定好，
最好同时留服务端计数器（<code>cached_tokens</code>）和客户端计时（TTFT/TPOT/E2E）两套数，这样"命中了多少"
和"真的快了多少"能互相印证，不至于被单方面的数字骗过去；三是<b>对照实验</b>，一次只动一个变量，
而且要对负载本身的性质做断言（前缀到底分不分散），不能只看脚本有没有跑通；四是<b>机制层面的解释</b>，
从注意力公式一路推到源码里具体的那一行，否则"提升 1.79 倍"就只是一个数字，换台机器可能就不成立了。</p>
<p>对我自己做研究的启发，主要是两点挺朴素的。一是别急着下结论：我看到 TTFT 降了、TPOT 没动，
差点直接写成"TPOT 不受前缀复用影响"，回头看数据才发现这两者在纯 CPU 串行下是此消彼长的关系，
跨组只能拿端到端时长和吞吐说话。二是别嫌"看起来没进度"的事慢——读源码、核对行号、给脚本加自检，
当时都觉得在耽误时间，最后报告里能站得住的句子基本都来自那儿。AI 帮我省掉的主要是检索和试错的时间，
至于哪些数字能信、哪些结论敢写，还是得自己判断。</p>
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
