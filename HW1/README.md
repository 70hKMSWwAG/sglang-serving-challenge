# HW1 - SGLang 推理服务部署与 Mooncake Workload 回放

第一次挑战：部署 SGLang OpenAI 兼容服务 → 采样 Mooncake trace 构造 workload → 绘制请求流程图 → 回答 RadixAttention / PagedAttention 相关问题。

## 交付文件

位于 `deliverables/`，共 6 份 PDF（与任务书要求的命名一一对应）：

| 文件 | 内容 |
|---|---|
| `操作保存.pdf` | 截图 1（服务启动 + `GET /v1/models` + 一次推理）与截图 2（Mooncake workload 回放）+ 附录（RadixCache 命中证据），共 4 页，**内嵌真机终端截图**（取自 `../envs/evidence/shot*.png`，环境①口径：20 条请求、12 vCPU） |
| `流程图.pdf` | 单次请求经过 SGLang 推理框架的完整流程（client → tokenizer → scheduler/queue → prefill → KV Cache/RadixCache → decode → sampling → streaming output → metrics） |
| `重点回答.pdf` | RadixAttention/RadixCache 解决的问题、page-sized KV cache 与 prefix reuse 对应 pipeline 位置、与 vLLM PagedAttention 的联系与差异 |
| `作业感受.pdf` | 完成过程、最困难部分与克服方式、对科研工作的启发 |
| `AI使用说明情况.pdf` | 使用的 AI 模型、提示词、AI 如何辅助学习 |
| `阅读文献笔记.pdf` | SGLang/RadixAttention（NeurIPS 2024）、vLLM/PagedAttention（SOSP 2023）、Mooncake（FAST'25）阅读笔记 |

> 另见 `env-sandbox/` 为同一题目在云沙箱（4 核 / 8 GB）环境下的独立复跑，结论一致。

## 环境

| 项目 | 取值 |
|---|---|
| 模型 | Qwen/Qwen3-0.6B |
| 推理框架 | SGLang 0.5.14（CPU 后端，`attention_backend=torch_native`，RadixCache 开启） |
| 截图来源（操作保存.pdf） | 真机 WSL2 · Ubuntu 26.04 · 12 vCPU / 15 GiB（环境①，原始证据见 `../envs/evidence/`） |
| results/ 默认口径 | 云主机 · Ubuntu 24.04 · 2 vCPU / 7.4 GB（环境③） |

两个环境的逐请求结果都保留在 `results/` 下；`操作保存.pdf` 的截图与 `results/wsl/` 一一对应（同为 20 条、trace 23608 条采样）。

`../envs/wsl/` 目录提供 WSL2 真机（12 vCPU / 15 GiB）一键复现脚本；`env-sandbox/` 提供云沙箱复现说明。

## 目录

```
HW1/
├── deliverables/               # 6 份 PDF（最终交付）
├── src/
│   ├── run_workload.py         # Mooncake workload 采样与回放（环境③口径）
│   └── make_shots_pdf.py       # 由 ../envs/evidence/shot*.png 生成操作保存.pdf（环境①口径）
└── results/
    ├── workload_results.jsonl  # 逐请求结果（环境③：2 vCPU 云主机）
    ├── workload_run.log / inference_response.json / models.json
    └── wsl/                    # 环境①（真机 12 vCPU）逐请求结果，与操作保存.pdf 截图对应
        ├── workload_results.jsonl / workload_run.log
        └── models.json / inference_response.json
```

## 回放

```bash
# 启动服务（示例，需先安装 SGLang，详见 ../envs/wsl/01_setup_env.sh 或 ../HW2/env-wsl/README.md）
python -m sglang.launch_server \
  --model-path Qwen/Qwen3-0.6B \
  --device cpu --attention-backend torch_native \
  --host 127.0.0.1 --port 30000

# 回放 workload（默认读取 HW1/results 同级 trace，需自行准备 mooncake_trace.jsonl）
python src/run_workload.py

# 指定 trace 与输出路径
TRACE=/path/to/mooncake_trace.jsonl OUT=/tmp/workload_results.jsonl python src/run_workload.py
```

脚本逻辑：从 Mooncake trace 在 `890 <= input_length <= 2048` 窗口采样 20 条记录，用固定词表构造等长 prompt，指数分布生成 Poisson 到达间隔（`LAMBDA=0.5`），并发流式发送到 `/generate` 并记录 TTFT / latency。
