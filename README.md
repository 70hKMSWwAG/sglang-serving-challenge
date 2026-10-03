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

| | ① `env1-wsl/` + `wsl/` + `evidence/` + `report/` | ② `sandbox-run/` | ③ `HW1/` + `HW2-0102603133/`（根目录） |
|---|---|---|---|
| 硬件 | 真机 WSL2，12 vCPU / 15 GiB | 云沙箱 4 核 / 8 GB，无 GPU | 云主机 2 vCPU / 7.4 GB，无 GPU |
| 系统 | Ubuntu 26.04 (WSL2) | Ubuntu 22.04 | Ubuntu 24.04 |
| SGLang 0.5.14 | 源码构建（sgl-kernel AVX2 基线补丁） | pip（CPU 引擎） | pip + vllm ops（torch_native） |
| HW2 实验输入 | 2112 tok（前缀 2048+64），run-1/run-2 换序复测 | 1024 tok（前缀 896+128），3 轮重复 | 512 tok（前缀 256+256），1 轮 |
| HW2 命中率结论 | **97.01% vs 0%**（两轮换序一致） | **89.79% vs 0.56%** | **50% vs 0%** |
| 交付位置 | `env1-wsl/HW2-0102603133/`（HW2 全套）+ `evidence/`、`report/src/`、`wsl/`、`HW1/results/env1-wsl/` | `sandbox-run/HW1/`、`sandbox-run/HW2/` | 根目录 `HW1/`、`HW2-0102603133/`（**最终交付，以此为准**） |

> ⚠️ 三个 `HW2-0102603133.zip` 同名但内容不同，注意区分：根目录 = 环境 ③、`sandbox-run/` 下 = 环境 ②、`env1-wsl/` 下 = 环境 ①（真机）。批改请以根目录版本为准。

三版输入长度与硬件不同，**绝对数值不可直接互比**，请看各组内的对照组对比。

## 🗂 目录总览

```
├── HW1/                      # ③ 第一关最终交付（6 份 PDF + 脚本 + 逐请求结果）
│   ├── README.md
│   ├── deliverables/         # 6 份 PDF：操作保存（真机截图1/2）/ 流程图 / 重点回答 / 作业感受 / AI使用说明 / 阅读文献笔记
│   ├── src/run_workload.py   # Mooncake workload 采样与回放
│   └── results/              # env3-cloud/（云主机口径）+ env1-wsl/（真机口径，与操作保存.pdf 截图对应）
├── HW2-0102603133/           # ③ 第二关最终交付
│   ├── README.md
│   ├── report.pdf            # 合订报告（任务一 + 任务二 + AI 使用说明）
│   ├── task1_results.pdf / task2_flow.pdf  # 任务一 / 任务二分册
│   ├── src/measure_prefix_cache.py / gen_pdfs.py
│   └── results/target1/      # dispersed_prefix / shared_prefix 逐请求结果 + comparison_table.json
├── HW2-0102603133.zip        # ③ 第二关打包（按作业要求命名，解压后仅含同名根目录）
│
├── env1-wsl/                 # ① 真机 WSL2 第二关完整交付（run-1/run-2 换序复测）
│   └── HW2-0102603133/       # report.pdf（8 页）/ 作业感受 / AI 使用说明 / src / results
│       └── HW2-0102603133.zip # ① 的打包（与本目录同名）
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
