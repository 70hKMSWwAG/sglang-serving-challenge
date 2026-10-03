# sglang-serving-challenge

学号：**0102603133**

> 本仓库包含同一套作业（第一关 + 第二关）在 **三个不同环境** 下的独立完成记录。
> 三版互不覆盖、并存保留，均可独立复现；**结论一致**（共享前缀组缓存命中率大幅更高、实际 Prefill token 大幅更少、TTFT 显著下降、TPOT 基本不变）。

## ⭐ 检查指引（批改入口）

| 想看什么 | 去哪里 |
|---|---|
| **最终交付打包（推荐）** | [`HW2-0102603133.zip`](HW2-0102603133.zip)（根目录，第二关）+ [`HW1/deliverables/`](HW1/deliverables/)（第一关 6 份 PDF） |
| 第二关实验数据与报告 | [`HW2-0102603133/`](HW2-0102603133/)（`report.pdf`、对照表、逐请求结果） |
| 第一关交付 PDF | [`HW1/deliverables/`](HW1/deliverables/)（6 份，含阅读文献笔记） |
| 复现脚本 | [`HW1/src/run_workload.py`](HW1/src/run_workload.py)、[`HW2-0102603133/src/measure_prefix_cache.py`](HW2-0102603133/src/measure_prefix_cache.py) |

## 📁 三个环境版本对照

| | ① `wsl/` + `evidence/` + `report/` | ② `sandbox-run/` | ③ `HW1/` + `HW2-0102603133/`（根目录） |
|---|---|---|---|
| 硬件 | 真机 WSL2，12 vCPU / 15 GiB | 云沙箱 4 核 / 8 GB，无 GPU | 云主机 2 vCPU / 7.4 GB，无 GPU |
| 系统 | Ubuntu 26.04 (WSL2) | Ubuntu 22.04 | Ubuntu 24.04 |
| SGLang 0.5.14 | 源码构建（AVX-512 补丁） | pip（CPU 引擎） | pip + vllm ops（torch_native） |
| HW2 实验输入 | 2112 tok（前缀 2048+64） | 1024 tok（前缀 896+128），3 轮重复 | 512 tok（前缀 256+256），1 轮 |
| HW2 命中率结论 | 共享组大幅更高 | **89.79% vs 0.56%** | **50% vs 0%** |
| 交付位置 | `evidence/`、`report/src/`、`wsl/`（WSL 版全量证据） | `sandbox-run/HW1/`、`sandbox-run/HW2/` | 根目录 `HW1/`、`HW2-0102603133/`（**最终交付，以此为准**） |

> ⚠️ `sandbox-run/HW2-0102603133.zip` 是环境 ② 的打包，**根目录 `HW2-0102603133.zip` 是环境 ③ 的打包**，两者同名但内容不同；批改请以根目录版本为准。

三版输入长度与硬件不同，**绝对数值不可直接互比**，请看各组内的对照组对比。

## 🗂 目录总览

```
├── HW1/                      # ③ 第一关最终交付（6 份 PDF + 脚本 + 逐请求结果）
│   ├── README.md
│   ├── deliverables/         # 7 份 PDF：操作保存（截图1/2）/ 操作说明 / 流程图 / 重点回答 / 作业感受 / AI使用说明 / 阅读文献笔记
│   ├── src/run_workload.py   # Mooncake workload 采样与回放
│   └── results/              # workload_results.jsonl / models.json / inference_response.json
├── HW2-0102603133/           # ③ 第二关最终交付
│   ├── README.md
│   ├── report.pdf            # 合订报告（任务一 + 任务二 + AI 使用说明）
│   ├── task1_results.pdf / task2_flow.pdf  # 任务一 / 任务二分册
│   ├── src/measure_prefix_cache.py / gen_pdfs.py
│   └── results/target1/      # dispersed_prefix / shared_prefix 逐请求结果 + comparison_table.json
├── HW2-0102603133.zip        # ③ 第二关打包（按作业要求命名，解压后仅含同名根目录）
│
├── wsl/                      # ① WSL 一键复现脚本（真机 12 vCPU）
├── evidence/                 # ① WSL 运行证据（日志 / 截图，见 evidence/README.md）
├── report/src/               # ① WSL 报告 HTML 源码（PDF 生成源）
├── tools/                    # ① WSL 辅助脚本（见 tools/README.md）
│
└── sandbox-run/              # ② 云沙箱完整复跑（含自己的 README，与根目录互不覆盖）
    ├── HW1/                  # 4 核环境第一关全套
    ├── HW2/                  # 4 核环境第二关全套
    ├── HW2-0102603133.zip    # ② 的打包（与根目录同名，注意区分）
    └── tools/                # 流程图生成 / 打包脚本
```
