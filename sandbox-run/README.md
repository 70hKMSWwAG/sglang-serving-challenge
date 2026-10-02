# sandbox-run：在无 GPU 云沙箱环境中的完整复跑

本目录是**同一套作业题目在另一套硬件环境下的独立复跑**，与仓库根目录原有的
WSL2（真机 12 vCPU / 15 GiB）版本**并存、互不覆盖**：

| | 根目录（原版） | `sandbox-run/`（本目录） |
|---|---|---|
| 硬件 | WSL2，Intel Core Ultra 5 338H，12 vCPU，15 GiB | 云沙箱容器，cgroup 限额 **4 核 / 8 GB**，无 GPU |
| 系统 | Ubuntu 26.04（WSL2） | Ubuntu 22.04 |
| SGLang 0.5.14 | 源码构建，CPU 后端需 AVX-512 补丁 | pip 安装，`SGLANG_USE_CPU_ENGINE=1` 启用 CPU 引擎 |
| HW1 交付 | `deliverables/` 六份 PDF | `sandbox-run/HW1/` 六份 PDF + 数据 + 脚本 |
| HW2 交付 | `HW2-林彦超.zip`（输入 2112 tok，前缀 2048+64） | `sandbox-run/HW2-林彦超.zip`（输入 1024 tok，前缀 896+128） |

两版结论一致：**共享前缀组命中率大幅更高、实际 Prefill token 大幅更少、TTFT 显著下降、TPOT 基本不变**。
绝对数值不可直接互比（CPU 核数、KV 池大小、输入长度都不同）。

## HW1 复跑结果（`HW1/`）

- 截图 1：`/v1/models` + 一次 `/v1/chat/completions` 推理；
- 截图 2：Mooncake FAST'25 arxiv-trace 采样 **24 条**请求（`input_length<=2048`、`output_length<=128` 窗口），
  指数间隔构造 **Poisson 到达**（均值 18 s，已调到服务容量以下），流式记录逐请求
  input tokens / output tokens / status / TTFT / latency；
- 实测：24/24 成功，`ttft p50=2.197 s / p95=4.138 s`，`latency p50=10.425 s / p95=26.327 s`，
  输出吞吐 3.548 token/s；
- 六份交付 PDF：`操作保存 / 流程图 / 重点回答 / 作业感受 / AI 使用说明情况 / 阅读文献笔记`。

## HW2 复跑结果（`HW2/`）

任务一（两组各 32 条、并发 8、`temperature=0 / max_new_tokens=16 / ignore_eos=true / sampling_seed=2026`，
原生 `/generate` 提交 `input_ids` + 流式；输入 1024 = 共享前缀 896 + 独立后缀 128；三轮 run-1/2/3 取平均）：

| 指标 | 共享前缀组 | 分散前缀组 |
|---|---|---|
| 成功率 | 100% | 100% |
| 缓存命中率 | **89.79%** | 0.56% |
| 实际 Prefill token | **3,344** | 32,583（−89.7%） |
| TTFT p50 | **6.458 s** | 18.423 s（−64.9%） |
| TPOT p50 | 0.599 s | 0.606 s（−1.1%，噪声级） |
| 端到端 p50 | **15.482 s** | 27.682 s（−44.1%） |
| 输出吞吐 | 8.26 tok/s | 4.62 tok/s（1.79×） |

任务二：`HW2/report.pdf` 第 4 页为 v0.5.14 源码级流程图（22 个编号节点，均标注 `文件:行号`），
第 5–6 页为关键函数表与四个问题的回答；所有行号都在本机安装的
`sglang 0.5.14` 源码上用 AST 逐条核验过（定义处 / 调用点分别标注）。

## 复现步骤

```bash
# 0) 模型：Qwen/Qwen3-0.6B（可从 ModelScope 下载）
#    https://www.modelscope.cn/models/Qwen/Qwen3-0.6B

# 1) 启动服务（CPU 后端必须先 export SGLANG_USE_CPU_ENGINE=1）
export SGLANG_USE_CPU_ENGINE=1 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
python3 -m sglang.launch_server \
  --model-path /workspace/models/Qwen3-0.6B \
  --device cpu --host 127.0.0.1 --port 30000 \
  --mem-fraction-static 0.045 --max-total-tokens 16384 --max-running-requests 16

# 2) HW1：等 /v1/models 就绪后回放 workload（如无 trace，先跑 scripts/fetch_trace.sh）
python3 HW1/scripts/mooncake_workload.py --num-requests 24 --mean-interval 18.0

# 3) HW2：任务一两组各 3 轮 + 汇总
bash HW2/scripts/run_all.sh
python3 HW2/src/target1/aggregate.py
```

## 环境注意（踩过的坑）

- SGLang 0.5.14 的 CPU 后端**必须** `export SGLANG_USE_CPU_ENGINE=1`，否则 RoPE 里
  `is_cpu()` 判定失败、报 `ModuleNotFoundError: vllm`（误导性极强）；
- 8 GB cgroup 下 `--mem-fraction-static` 要压到 0.045、`--max-total-tokens 16384`，
  否则 Scheduler 会被 OOM kill（`memory.events` 里 `oom_kill` 计数会 +1，而宿主机 `free` 看不出来）；
- `POST /flush_cache` 成功返回 `Cache flushed.`（另有一行括号说明），判定空闲要以它为准。

## 目录

```
sandbox-run/
├── README.md                  # 本文件
├── HW1/                       # 第一次挑战全套（六份 PDF + data/ + scripts/ + results/ + screenshots/）
├── HW2/                       # 第二次挑战全套（report.pdf + src/ + results/ + figures/ + scripts/）
├── HW2-林彦超.zip              # 按任务书要求打包（解压后仅含同名根目录）
└── tools/                     # 流程图生成 / HW2 打包脚本
```
