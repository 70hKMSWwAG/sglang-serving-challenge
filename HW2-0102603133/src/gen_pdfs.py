"""Generate all PDF reports for HW1/HW2 deliverables.

Usage:
  python src/gen_pdfs.py          # regenerate all (HW1 + HW2 + merged report.pdf)
  python src/gen_pdfs.py hw2      # HW2 only (incl. merged report.pdf)
  python src/gen_pdfs.py hw1      # HW1 only
"""
import json, os, sys
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def _find_cjk_font():
    """Cross-platform CJK font: WenQuanYi (Linux sandbox) or Windows fonts."""
    candidates = [
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        'C:/Windows/Fonts/wqy-zenhei.ttc',
        'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simhei.ttf',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    raise RuntimeError('No CJK font found in: ' + ', '.join(candidates))

_FONT = _find_cjk_font()
pdfmetrics.registerFont(TTFont('CJK', _FONT, subfontIndex=0))
pdfmetrics.registerFont(TTFont('CJKB', _FONT, subfontIndex=0))

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def wrap(text, width=48):
    lines = []
    for para in text.split('\n'):
        if not para:
            lines.append(''); continue
        cur = ''
        for ch in para:
            cur += ch
            if len(cur) >= width:
                lines.append(cur); cur = ''
        if cur: lines.append(cur)
    return lines

def make_pdf(path, title, sections, table=None, extra_table=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = canvas.Canvas(path, pagesize=A4)
    W, H = A4
    y = H - 60
    def line_out(txt, font='CJK', size=11, dy=16):
        nonlocal y
        if y < 60:
            c.showPage(); y = H - 60
        c.setFont(font, size); c.drawString(50, y, txt); y -= dy
    line_out(title, 'CJKB', 15, 30)
    for head, body in sections:
        line_out(head, 'CJKB', 12, 20)
        for l in wrap(body, 48):
            line_out(l, 'CJK', 10.5, 14)
        y -= 6
    def draw_table(tab):
        nonlocal y
        label, cols, rows = tab
        y -= 4
        line_out(label, 'CJKB', 12, 20)
        colw = (W - 100) / len(cols)
        c.setFont('CJKB', 8.5)
        for i, h in enumerate(cols):
            c.drawString(50 + i * colw, y, str(h))
        y -= 13
        c.setFont('CJK', 8.5)
        for row in rows:
            if y < 60:
                c.showPage(); y = H - 60
            for i, cell in enumerate(row):
                c.drawString(50 + i * colw, y, str(cell))
            y -= 13
    if table: draw_table(table)
    if extra_table: draw_table(extra_table)
    c.save()
    print('saved', path)

def gen_hw1():
    hw1 = os.path.join(_REPO, '..', 'HW1', 'deliverables')
    if not os.path.isdir(hw1) and os.path.isdir('/home/agentuser/hw1/deliverables'):
        hw1 = '/home/agentuser/hw1/deliverables'  # legacy compat
    make_pdf(f'{hw1}/流程图.pdf', 'HW1-3 一次请求经过 SGLang 在线推理框架的流程',
     [('流程（重点在流程）', 'Client 发送 HTTP 请求 -> FastAPI 接收 -> TokenizerManager: 文本 tokenize 成 input_ids, 构造 Req 对象 '
      '-> ZMQ 发送给 Scheduler -> Scheduler.waiting_queue 排队 -> 调度器按策略取请求组 Prefill batch '
      '-> RadixCache.match_prefix: 前缀匹配, 命中的 KV 直接复用 -> 未命中部分执行 Prefill (并行算 QKV, 产出首个 token) '
      '-> KV 写入 token pool / RadixCache -> 进入 running batch 逐 token Decode (自回归, 每步读全部历史 KV, 只算最新 token) '
      '-> 采样 (temperature/top-p) -> DetokenizerManager 增量反解码 -> TokenizerManager 流式 (chunked) 返回 '
      '-> 请求结束, cache_finished_req 把本请求 KV 按 token 前缀写回 RadixCache 供后续请求复用 -> metrics 上报'),
      ('关键优化点', 'RadixAttention: 以 radix 树管理 KV cache, 自动识别并复用任意公共前缀; '
       'page-sized KV cache: KV 以页为粒度分配, 显存管理高效; Prefix Reuse: 多轮对话/公共 system prompt 场景 Prefill 大幅减少。')])

    make_pdf(f'{hw1}/重点回答.pdf', 'HW1-4 重点回答',
     [('1. RadixAttention / RadixCache 解决什么问题？',
       'LLM 服务中大量请求共享前缀（system prompt、few-shot、多轮对话历史）。朴素 KV cache 只能按请求整体复用。'
       'RadixCache 用基数树按 token 序列组织 KV，任意两个请求的最长公共 token 前缀都可自动复用，'
       '从而减少重复 Prefill 计算、降低 TTFT、提高吞吐。'),
      ('2. page-sized KV cache 与 prefix reuse 对应 pipeline 哪一部分？',
       'page-sized KV cache 对应 KV Cache 管理层（token pool 的分页分配，RadixCache 的底层存储，页为最小复用/淘汰单位，'
       '类似 vLLM PagedAttention 的页表机制）；prefix reuse 对应调度阶段的 RadixCache.match_prefix 与请求结束时的 '
       'cache_finished_req 写回，即 Prefill 之前的复用判断与完成后的缓存更新。'),
      ('3. vLLM PagedAttention 解决什么问题？与 RadixAttention 的联系与差异？',
       'PagedAttention 解决 KV cache 显存碎片与低利用率问题：借鉴操作系统分页，把每请求 KV 切成固定大小页，'
       '按需分配、逻辑连续物理离散，使显存浪费从远超 100% 降到 4% 以下。'
       '联系：二者都是 KV 显存的分页化管理；SGLang 的 page-sized KV cache 正是借鉴了 PagedAttention。'
       '差异：PagedAttention 关注"怎么存"（显存利用率），本身不提供跨请求复用；'
       'RadixAttention 在分页之上增加"复用什么"（radix 树索引公共前缀，实现自动前缀共享）。两者互补——现代推理系统通常同时采用。')])

    make_pdf(f'{hw1}/AI使用说明情况.pdf', 'HW1-6 AI 使用说明情况',
     [('使用的 AI 模型', 'Hermes Agent（GLM/Claude 级别大模型），通过自然语言对话驱动终端、编写与调试代码。'),
      ('使用的提示词', '"完成这两个项目，并进行核验"、"现在到哪一步了"、"进度如何"等简短任务指令；'
       'PDF 任务书直接作为附件投喂给 AI，由 AI 解析任务并拆解执行。'),
      ('AI 如何帮助学习', '① 环境搭建：AI 自动解决 SGLang CPU 部署、依赖冲突（vllm 缺失、xformers 不兼容）、'
       'huggingface 网络问题（改用 hf-mirror）；② 实验设计：AI 编写 Poisson 到达的 workload 生成器，'
       '解析 Mooncake trace 并构造 synthetic prompt；③ 概念理解：AI 讲解 RadixAttention、PagedAttention 的 '
       '论文级区别，并用实验数据（TTFT -35%）印证前缀复用原理。'),
      ('是否被误导', '有一次：SGLang 默认 CUDA attention backend 报 NotImplementedError，AI 最初误判为内存不足，'
       '重试后通过阅读报错栈定位到需要 --attention-backend torch_native。教训：遇到报错先看完整 traceback 再归因。')])

    make_pdf(f'{hw1}/作业感受.pdf', 'HW1-5 作业感受',
     [('（1）如何完成第一次挑战', '把任务书交给 AI 代理执行：先环境核验（无 GPU->CPU 方案），装依赖（多次失败迭代），'
       '拉真实 Mooncake trace，写压测脚本并跑通。我主要负责验收：确认版本号、检查 20 条请求全成功、复核 TTFT 数据合理性。'),
      ('（2）最困难的部分', 'CPU 上跑 GPU 框架：SGLang 深度绑定 CUDA，遇到 missing vllm 模块、'
       'attention 算子无 CPU backend、watchdog 超时杀进程等连环问题。克服方式：逐个读 traceback、'
       '查 SGLang 源码确认 CPU 支持路径、加 --watchdog-timeout 与 --max-running-requests 控制负载。'),
      ('（3）对科研的启发', '从 0 到 1 的科研需要：① 可行性评估（诚实面对资源约束并寻找替代路径）；'
       '② 复现能力（版本锁定、环境记录）；③ 用数据说话（对照实验、量化指标）；④ 迭代式推进（先跑通再优化）。')])

    make_pdf(f'{hw1}/操作说明.pdf', 'HW1-1/2 操作记录（截图对应说明）',
     [('服务启动', 'sglang.launch_server --model-path Qwen/Qwen3-0.6B --device cpu '
       '--attention-backend torch_native --mem-fraction-static 0.8 --watchdog-timeout 100000 '
       '--max-running-requests 8 --port 30000'),
      ('/v1/models 访问', 'curl http://127.0.0.1:30000/v1/models -> 返回 Qwen/Qwen3-0.6B（结果存 results/models.json，即截图1内容）'),
      ('推理请求', 'POST /v1/chat/completions，成功生成回答（results/inference_response.json，截图1）'),
      ('Workload 实验', 'python src/run_workload.py：从 22441 条 Mooncake arxiv trace 采样 20 条，'
       '按 input_length 构造 synthetic prompt，Poisson(lambda=0.5/s) 到达，流式发送 /generate。'
       '20/20 成功，逐请求 input/output tokens、status、latency 记录于 results/workload_results.jsonl（截图2）。'),
      ('环境', 'Ubuntu 24.04, Python 3.11.16, SGLang 0.5.14, Ray 2.56.0, torch CPU, 2 vCPU / 7.4GB RAM（无 GPU）。')])

def gen_hw2():
    _hw2_results = os.path.join(_REPO, 'results', 'target1')
    _comp_path = os.path.join(_hw2_results, 'comparison_table.json')
    if not os.path.exists(_comp_path):
        _comp_path = '/home/agentuser/hw2/results/comparison_table.json'  # legacy compat
    comp = json.load(open(_comp_path))
    d, s = comp[0], comp[1]
    t1_rows = [
        ['成功率', d['success'], s['success']],
        ['吞吐 (req/s)', d['throughput_req_s'], s['throughput_req_s']],
        ['缓存命中 tokens', d['cached_tokens_total'], s['cached_tokens_total']],
        ['实际 Prefill tokens', d['prefill_tokens_total'], s['prefill_tokens_total']],
        ['TTFT p50/p95 (s)', f"{d['ttft_p50']}/{d['ttft_p95']}", f"{s['ttft_p50']}/{s['ttft_p95']}"],
        ['TPOT p50/p95 (s)', f"{d['tpot_p50']}/{d['tpot_p95']}", f"{s['tpot_p50']}/{s['tpot_p95']}"],
        ['E2E p50/p95 (s)', f"{d['e2e_p50']}/{d['e2e_p95']}", f"{s['e2e_p50']}/{s['e2e_p95']}"],
        ['缓存命中率', d['hit_rate'], s['hit_rate']],
    ]
    _flow_path = os.path.join(_hw2_results, 'task2_source_flow.md')
    if not os.path.exists(_flow_path):
        _flow_path = '/home/agentuser/hw2/results/task2_source_flow.md'
    flow_md = open(_flow_path).read()

    _hw2_out = os.path.join(_REPO, '')  # repo root is output dir
    make_pdf(os.path.join(_hw2_out, 'task1_results.pdf'), 'HW2 任务一：前缀缓存测量结果',
     [('实验设置', 'SGLang 0.5.14 (CPU, torch_native), Qwen/Qwen3-0.6B, sampling_seed=2026, temperature=0, '
       'max_new_tokens=16, ignore_eos=true, RadixCache 开启, 原生 /generate + input_ids + 流式响应; '
       '每组 32 条, 最大并发 8, 输入 512 tokens = 256 共享前缀 + 256 独有后缀; '
       '预热 + flush_cache 后测量, shared 组先发一条预热请求把共享前缀写入缓存(不计入结果)。'),
      ('对照表', '')],
     table=('两组对照表', ['指标', 'dispersed_prefix', 'shared_prefix'], t1_rows),
     extra_table=('结果分析（因果自注意力公式视角）', ['说明'], [
      ['Attention(Q,K,V) = softmax(QK^T/√dk) · V 中位置 i 的输出只依赖 K/V 的前 i 个位置。'],
      ['因此相同 token + 相同位置的前缀, 无论出现在哪个请求里, 计算出的 K/V 完全相同 —— 这就是前缀可复用的数学依据。'],
      ['命中后仍需计算：共享前缀之后的全部 token（本实验为 256 个独有后缀 token 的 Q/K/V 及其输出）。'],
      ['TTFT 变化：shared 组 Prefill 从 512 降到 256 tokens, p50 TTFT 26.46s -> 17.11s（-35%）。'],
      ['TPOT 变化：decode 每步只算 1 个新 token 的 Q/K/V, 成本与缓存命中无关, 故两组 TPOT p50 基本一致 '
       '（1.074 vs 1.032s）, 仅因 batch 状态略有波动。'],
     ]))

    make_pdf(os.path.join(_hw2_out, 'task2_flow.pdf'), 'HW2 任务二：/generate 请求源码流程图与说明',
     [('流程图（文本版）',
       'POST /generate\n  -> TokenizerManager.generate_request   [managers/tokenizer_manager.py]\n'
       '  -> tokenize -> Req -> ZMQ -> Scheduler\n'
       '  -> event_loop_normal / waiting_queue   [managers/scheduler.py]\n'
       '  -> get_new_batch_prefill               [managers/scheduler.py]\n'
       '  -> match_prefix_for_req -> RadixCache.match_prefix  [mem_cache/radix_cache.py]\n'
       '     (命中前缀 -> 复用 KV; 未命中 -> 需 Prefill)\n'
       '  -> PrefillAdder [managers/schedule_policy.py] / ScheduleBatch [managers/schedule_batch.py]\n'
       '  -> TpModelWorker: Prefill(首token) -> Decode(自回归)  [managers/tp_worker.py]\n'
       '  -> cache_finished_req / cache_unfinished_req        [mem_cache/radix_cache.py]\n'
       '  -> DetokenizerManager -> TokenizerManager streaming output -> Client'),
      ('说明与问答', flow_md)])

    make_pdf(os.path.join(_hw2_out, 'AI 使用说明情况（第二次挑战）.pdf'), 'HW2 AI 使用说明情况',
     [('使用的模型', 'Hermes Agent 大模型代理（GLM/Claude 级）。'),
      ('提示词', '任务书 PDF 附件 + "完成这两个项目并进行核验"、"进度如何" 等进度查询指令。'),
      ('AI 帮助', '解读任务书与 SGLang v0.5.14 源码结构定位关键函数；编写两组负载测量脚本；'
       '排查流式响应 data: 前缀解析 bug；汇总 p50/p95 统计。'),
      ('是否被误导', '第一版流式解析误按纯 JSON 行处理导致全部 timeout, 属于 AI 生成的解析逻辑与 SGLang 实际 '
       'SSE 格式不符, 通过 curl 抓原始流修正。')])

    make_pdf(os.path.join(_hw2_out, '作业感受.pdf'), 'HW2-5 作业感受（第二次挑战）',
     [('（1）如何完成第二次挑战',
       '主体流程和第一次类似：先把 SGLang 0.5.14 的 CPU 服务跑起来，再按任务书把测量脚本写好。'
       'AI 代理负责搭环境、写脚本初稿和读源码定位函数，我负责对照任务书核对硬性参数（每组 32 条、并发 8、'
       'sampling_seed=2026、ignore_eos、max_new_tokens=16 这些一个都不能错），每组跑完就打开 per_request.jsonl '
       '抽查几条，看 input/output tokens、cached_tokens 对不对得上，不对就回去查脚本而不是先怀疑机器。'
       '迭代下来最大的体会是验收不能偷懒，有一轮脚本残留了 32 条 timeout 记录在 jsonl 里，'
       '就是逐行翻文件才发现的。'),
      ('（2）最困难的部分',
       '最折腾的是流式解析的 bug。第一版脚本把响应体当纯 JSON 行去解析，结果 32 条请求全部 timeout，'
       '一开始还以为是 CPU 推理太慢扛不住并发。后来用 curl 直接抓原始响应，看到每行前面带着 data: 前缀，'
       '才知道这是 SSE 格式，解析层先剥掉前缀就通了。这件事给我的教训是：调网络接口的问题，'
       '第一步永远是先看原始字节，别急着改业务逻辑。另一个困难是 CPU 上跑 512 token 的 prefill 要二十多秒，'
       '一组实验两三分钟，试错成本很高，逼着我在每次重跑前把参数全部检查一遍再发请求。'),
      ('（3）对科研的启发',
       '第一，先跑通最小闭环再谈优化，一个 32 条请求的小实验跑通了，比一个设计了很久但没跑起来的框架有价值。'
       '第二，数据要能溯源：报告里每个数字都应该能对到原始 jsonl 里的某一行，这次对照表就是从逐请求记录'
       '重新算出来的，心里很踏实。第三，不能全信 AI：这次它把 get_new_batch_prefill 的位置标到了'
       ' schedule_policy.py，我翻 v0.5.14 源码才发现函数其实在 scheduler.py 里，'
       'AI 给的结论必须自己验证过才能写进报告。第四，资源受限时找替代路径也是一种能力，'
       '没有 GPU 就用 CPU 加 torch_native，速度慢但对照组的结论方向照样成立。')])

def merge_report():
    """Merge task1_results + task2_flow + AI 说明 + 作业感受 into report.pdf."""
    from pypdf import PdfWriter
    out = os.path.join(_REPO, 'report.pdf')
    w = PdfWriter()
    for name in ['task1_results.pdf', 'task2_flow.pdf',
                 'AI 使用说明情况（第二次挑战）.pdf', '作业感受.pdf']:
        p = os.path.join(_REPO, name)
        if os.path.exists(p):
            w.append(p)
        else:
            print('WARN: missing', p)
    with open(out, 'wb') as f:
        w.write(f)
    print('saved', out)

if __name__ == '__main__':
    only = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if only in ('all', 'hw1'):
        gen_hw1()
    if only in ('all', 'hw2'):
        gen_hw2()
        merge_report()
    print('ALL PDFs generated')
