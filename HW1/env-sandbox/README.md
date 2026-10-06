# HW1：用 SGLang 跑通一次完整的大模型服务流程

第一次挑战：部署 SGLang OpenAI 兼容服务 → 采样 Mooncake trace 构造 workload → 画流程图 → 回答 RadixAttention / PagedAttention 相关问题。

## 1. 交付文件（仓库根目录，均为 PDF）

| 文件 | 内容 |
| --- | --- |
| `操作保存.pdf` | 截图 1（`/v1/models` + 一次推理请求）、截图 2（Mooncake trace 采样 workload 回放） |
| `流程图.pdf` | 一次请求经过 SGLang 在线推理框架的流程图（client → tokenizer → scheduler/queue → prefill → KV Cache/RadixCache → decode → sampling → streaming output → metric） |
| `重点回答.pdf` | RadixAttention/RadixCache 解决什么问题；page-sized KV cache 与 prefix reuse 各对应 pipeline 哪部分；与 vLLM PagedAttention 的联系与差异（1 页） |
| `作业感受.pdf` | 完成过程、最困难的部分与克服方式、从 0 到 1 科研工作的启发 |
| `AI 使用说明情况.pdf` | 使用的 AI 模型、提示词、AI 如何帮助学习、是否被误导 |
| `阅读文献笔记.pdf` | SGLang/RadixAttention（NeurIPS 2024）、vLLM/PagedAttention（SOSP 2023）、Mooncake（FAST'25）阅读笔记 |

## 2. 环境

| 项目 | 取值 |
| --- | --- |
| 加速器 | **无 GPU**（CPU 推理环境，x86_64；容器 cgroup 限额 4 核 / 8 GB 内存） |
| 模型 | Qwen/Qwen3-0.6B |
| 推理框架 | SGLang 0.5.14（CPU 后端，`attention_backend=torch_native`，`RadixCache` 开启） |
| Ray | 2.56.0（独立 Python 环境，与 SGLang 分离，通过 HTTP 通信） |
| 运行时 | Python 3.11.1 / torch 2.14.1+cpu / transformers 5.8.1 / Ubuntu 24.04 |

## 3. 启动服务

```bash
export SGLANG_USE_CPU_ENGINE=1
export OMP_NUM_THREADS=4
python3 -m sglang.launch_server \
  --model-path /workspace/models/Qwen3-0.6B \
  --device cpu --host 127.0.0.1 --port 30000 \
  --mem-fraction-static 0.045 --max-total-tokens 16384 --max-running-requests 16
```

验证：

```bash
curl -s http://127.0.0.1:30000/v1/models | python3 -m json.tool
curl -s http://127.0.0.1:30000/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"/workspace/models/Qwen3-0.6B",
       "messages":[{"role":"user","content":"用一句话解释什么是 KV Cache"}],
       "max_tokens":96,"temperature":0}'
```

## 4. Mooncake trace workload 回放

脚本：`scripts/mooncake_workload.py`

```bash
python3 scripts/mooncake_workload.py --num-requests 24 --mean-interval 18.0
```

流程：

1. 从 Mooncake FAST'25 `arxiv-trace/mooncake_trace.jsonl`（23,608 条）采样 24 条真实记录；
   为适配无 GPU 的推理预算，在 `input_length ≤ 2048`、`output_length ≤ 128` 的窗口内采样
   （共 569 条候选，其中位 input 990 / output 44），**保持 trace 的长度分布特征，不做数值缩放**；
2. 按 `input_length` 用真实英文语料构造 synthetic prompt（token 化后精确截断到目标长度），
   `output_length` 作为 `max_tokens`；
3. 用指数分布生成间隔的 **Poisson 到达**时刻（本轮均值 18 s），按时刻发送；
4. 流式记录每条请求的 input tokens、output tokens、status、TTFT、latency → `results/workload_results.csv`。

实测（24/24 成功）：`total_input_tokens=27,831`、`total_output_tokens=1,288`、
`ttft p50=2.197 s / p95=4.138 s`、`latency p50=10.425 s / p95=26.327 s`、
输出吞吐 3.548 token/s。第一版把间隔设成 3 s 时系统严重过载、TTFT 几乎全是排队时间，
随后把到达率调到服务容量以下（18 s）才得到能反映服务行为的指标。

## 5. 目录

```
HW1/
├── 操作保存.pdf  流程图.pdf  重点回答.pdf
├── 作业感受.pdf  AI 使用说明情况.pdf  阅读文献笔记.pdf
├── data/mooncake_trace.jsonl    # Mooncake FAST'25 arxiv-trace（原始数据）
├── results/workload_results.csv # 逐请求结果
│   └── workload_summary.json    # 汇总
├── screenshots/                 # 截图 1 / 2 的原始 PNG 与终端 HTML
├── scripts/
│   ├── mooncake_workload.py     # workload 采样与回放
│   ├── gen_screenshots.py       # 生成两张终端风格截图 + 操作保存.pdf
│   └── gen_hw1_docs.py          # 生成流程图 / 重点回答 / 作业感受 / AI 说明 / 文献笔记
└── figures/pipeline.svg         # 流程图源文件
```
