# HW2：SGLang 前缀缓存测量与请求流程源码阅读

承接第一次挑战，完成两件事：**测量 SGLang RadixCache 前缀缓存的效果**，以及**沿主线阅读 SGLang v0.5.14 中一条 `/generate` 请求的处理流程**。

## 1. 环境

| 项目 | 取值 |
| --- | --- |
| 加速器 | **无 GPU**（CPU 推理环境，x86_64；容器 cgroup 限额 4 核 / 8 GB 内存） |
| 模型 | Qwen/Qwen3-0.6B（本地权重 `/workspace/models/Qwen3-0.6B`） |
| 推理框架 | SGLang 0.5.14（CPU 后端，attention backend 自动回退为 `torch_native`） |
| Ray | 2.56.0（独立 Python 环境 `/opt/sgl-venv`，按题目要求与 SGLang 分环境、通过 HTTP 通信） |
| 运行时 | Python 3.11.1 / torch 2.14.1+cpu / transformers 5.8.1 / Ubuntu 24.04 |

> 说明：本机没有 GPU，因此所有实验都在 SGLang 的 **CPU 后端**上完成，绝对延迟数值与 GPU 环境不可直接比较；但缓存命中率、实际 Prefill token 数、两组之间的相对差异由 CPU 后端同样成立（日志可见 `Tree cache initialized: impl=RadixCache`，前缀缓存确实开启并生效）。

## 2. 安装

```bash
# SGLang（主环境）
pip3 install torch==2.10.0+cpu --index-url https://download.pytorch.org/whl/cpu
pip3 install --no-deps sglang==0.5.14
pip3 install transformers==5.8.1 openai==2.6.1 compressed-tensors aiohttp fastapi uvicorn \
            pydantic orjson msgspec requests pyzmq setproctitle psutil prometheus-client \
            partial_json_parser einops xgrammar blobfile==3.0.0 aiohttp
pip3 install torchvision --index-url https://download.pytorch.org/whl/cpu   # sglang 需要 torchvision.io

# Ray（独立环境，与 SGLang 分离）
python3 -m venv /opt/sgl-venv && /opt/sgl-venv/bin/pip install ray==2.56.0

# 模型权重（本仓库不含权重；可用任意来源下载到 /workspace/models/Qwen3-0.6B）
```

## 3. 启动服务

```bash
export SGLANG_USE_CPU_ENGINE=1      # CPU 后端必需；否则 RoPE 等分支会走到 CUDA 路径
export OMP_NUM_THREADS=4
python3 -m sglang.launch_server \
  --model-path /workspace/models/Qwen3-0.6B \
  --device cpu \
  --host 127.0.0.1 --port 30000 \
  --mem-fraction-static 0.045 \
  --max-total-tokens 16384 \
  --max-running-requests 16
```

启动日志中确认两点：`max_total_num_tokens=...` 与 `Tree cache initialized: source=default impl=RadixCache`。

## 4. 脚本用途与回放命令

| 路径 | 用途 |
| --- | --- |
| `src/target1/run_benchmark.py` | 任务一基准：一组 32 条请求、并发 8，原生 `/generate` 提交 `input_ids` + 流式响应；负责服务预热、等待空闲、`/flush_cache` 确认、共享前缀组预热请求、逐请求采集指标 |
| `src/target1/aggregate.py` | 汇总 run-{1,2,3}，生成 `results/target1/summary.{md,json}`（主表与逐轮明细） |
| `src/make_report.py` | 生成 `report.pdf`（正文 6 页）：实验表格、公式图、流程图页与源码说明 |

```bash
# 任务一：两组各跑 3 轮
python3 src/target1/run_benchmark.py --group shared_prefix    --run-id run-1
python3 src/target1/run_benchmark.py --group dispersed_prefix --run-id run-1
# ...run-2 / run-3 同理（scripts/run_all.sh 一次性跑完 3 轮）

python3 src/target1/aggregate.py    # -> results/target1/summary.md
python3 src/make_report.py          # -> report.pdf
```

关键参数（与挑战要求一致）：`temperature=0`、`max_new_tokens=16`、`ignore_eos=true`、
`sampling_seed=2026`、接口 `/generate` + `input_ids` + `stream=true`、32 条/组、最大并发 8。

## 5. 结果目录

```
results/target1/
├── summary.md                       # 主表 + 逐轮明细（人类可读）
├── summary.json                     # 同上，机器可读（report.pdf 直接读取此文件）
├── shared_prefix/
│   ├── run-1|run-2|run-3/
│   │   ├── per_request.jsonl        # 逐请求：ttft / tpot / e2e / prompt_tokens / cached_tokens ...
│   │   └── summary.json             # 该轮汇总
│   └── run-N.log                    # 该轮完整日志（含 flush_cache 确认、预热请求）
└── dispersed_prefix/                # 结构同上
```

## 6. 报告表格 ↔ 原始结果对应

| report.pdf 中的内容 | 数据来源 |
| --- | --- |
| 1.2 对照主表（三轮均值） | `results/target1/summary.json` 的 `mean` 字段（由 `aggregate.py` 汇总） |
| 1.4 逐轮明细表 | `results/target1/summary.json` 的 `per_run` 字段；即各组 `run-{1,2,3}/summary.json` |
| 1.4 的单请求口径数字（TTFT/TPOT/prefill token） | `results/target1/{组}/run-N/per_request.jsonl`（每行一条请求） |
| 2 流程图 | 矢量源文件 `figures/request_flow.svg`（生成脚本 `tools/gen_flowcharts.py`，随本目录一并打包） |
| 3.1 函数与行号表、3.2 回答 | 对照本地 `sglang 0.5.14` 源码（`site-packages/sglang/srt/...`）逐条核对 |

## 7. 主要结论（摘要）

共享前缀组相对分散前缀组：缓存命中率 **89.79% vs 0.56%**，实际执行 Prefill 的 token 数
**3,344 vs 32,583（−89.7%）**，TTFT p50 **6.46 s vs 18.42 s（−64.9%）**，TPOT p50
**0.599 s vs 0.606 s（−1.1%，基本不变）**，端到端 p50 **15.48 s vs 27.68 s（−44.1%）**，
输出吞吐 **8.26 vs 4.62 token/s（1.79×）**。两组 32 条请求均 100% 成功、输入输出长度一致。
