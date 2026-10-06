# sglang-serving-challenge

学号：**0102603133**

三次挑战（HW1 熟悉 SGLang / HW2 前缀缓存与请求流程 / HW3 Ray Serve 路由对比与改进）
的全部交付物、实验结果与复现脚本。目录按「**作业 × 环境**」两级组织：顶层是作业，
每个作业内部再按完成环境/实现版本分目录。

## ⭐ 批改入口

| 作业 | 最终交付位置 | 说明 |
|---|---|---|
| HW1 | [`HW1/deliverables/`](HW1/deliverables/) | 6 份 PDF；逐请求结果见 [`HW1/results/`](HW1/results/) |
| HW2 | [`HW2/env-wsl/`](HW2/env-wsl/) | 真机 WSL2 版，数据最完整（run-1/run-2 换序复测），report.pdf 8 页 |
| HW3 | [`HW3/ray-serve-4gpu/`](HW3/ray-serve-4gpu/) | 4 × 4090D（AutoDL）版，符合任务书「四张 GPU」要求；report.pdf + 作业感受 PDF + AI 使用说明 PDF 齐备 |

> **第三关交付包**：根目录 [`HW3-0102603133.zip`](HW3-0102603133.zip)，解压后仅含同名
> 根目录（`README.md` / `report.pdf` / `AI 使用说明情况（第三次挑战）.pdf` /
> 作业感受 PDF / `src/{target1,target3}` / `results/{target1,target3}`），符合任务书交付格式。
> 需要重新打包时运行 `python scripts/build_deliverable_zips.py`；加 `--all` 可一并生成 HW2 包。

## 🗂 目录总览

```
├── HW1/                          # 第一关：SGLang 部署与 Mooncake workload 回放
│   ├── deliverables/             #   6 份交付 PDF（操作保存/流程图/重点回答/感受/AI使用/文献笔记）
│   ├── src/                      #   采样与回放脚本
│   ├── results/{cloud,wsl,sandbox}/   # 逐请求结果，按环境分列
│   └── env-sandbox/              #   ② 云沙箱（4 核 8 GB）完整复跑存档
├── HW2/                          # 第二关：前缀缓存测量 + 请求流程分析
│   ├── env-wsl/                  #   ① 真机 WSL2【最终交付】run-1/run-2 换序复测
│   ├── env-sandbox/              #   ② 云沙箱复跑存档
│   └── env-cloud/                #   ③ 云主机存档
├── HW3/                          # 第三关：Ray Serve 路由对比（A/B/C/D）与改进
│   ├── ray-serve-1gpu/           #   单卡 4090D（SeetaCloud）主版本，含全套脚本与 router 日志
│   └── ray-serve-4gpu/           #   4 卡 4090D（AutoDL）版本，含作业感受与 AI 使用说明 PDF
├── envs/                         # 环境级辅助资产（不属于单个作业）
│   ├── wsl/                      #   ① WSL 一键复现脚本
│   ├── evidence/                 #   ① 运行证据（日志/截图）
│   ├── report/                   #   ① 报告 HTML 源码（PDF 生成源）
│   ├── tools/{wsl,sandbox}/      #   各环境辅助脚本
│   ├── reference/                #   任务书原文截图
│   └── sandbox-index.md          #   ② 云沙箱存档入口说明
└── scripts/                      # 仓库工具（交付 zip 重建等）
```

## 三环境对照（HW2 实验口径）

| | ① `HW2/env-wsl/` | ② `HW2/env-sandbox/` | ③ `HW2/env-cloud/` |
|---|---|---|---|
| 硬件 | 真机 WSL2，12 vCPU / 15 GiB | 云沙箱 4 核 / 8 GB，无 GPU | 云主机 2 vCPU / 7.4 GB，无 GPU |
| 系统 | Ubuntu 26.04 (WSL2) | Ubuntu 22.04 | Ubuntu 24.04 |
| SGLang 0.5.14 | 源码构建（sgl-kernel AVX2 基线补丁） | pip（CPU 引擎） | pip + vllm ops（torch_native） |
| 实验输入 | 2112 tok（前缀 2048+64），run-1/run-2 换序复测 | 1024 tok（前缀 896+128），3 轮重复 | 512 tok（前缀 256+256），1 轮 |
| 命中率结论 | **97.01% vs 0%**（两轮换序一致） | **89.79% vs 0.56%** | **50% vs 0%** |

三版输入长度与硬件不同，**绝对数值不可直接互比**，请看各组内的对照组对比；
三版结论一致：共享前缀组缓存命中率大幅更高、实际 Prefill token 大幅更少、
TTFT 显著下降、TPOT 基本不变。

## HW3 两个版本

| | [`HW3/ray-serve-4gpu/`](HW3/ray-serve-4gpu/) **← 交付版** | [`HW3/ray-serve-1gpu/`](HW3/ray-serve-1gpu/) |
|---|---|---|
| 硬件 | 4 × RTX 4090D（AutoDL 北京 B2 区），符合任务书「每人四张 GPU」 | 1 × RTX 4090D（SeetaCloud 容器），单卡跑 4 个后端，与任务书有偏差 |
| 拓扑 | 4 副本各占一卡，逐 worker 隔离 | 单卡四后端，Ray Serve 代理 :8000 |
| 轮次 | A / B1 / B2 / C / D 五轮 | A / B1 / B2 / C / D 多轮（`run_all_rounds.sh`，run-1 层级） |
| 产出 | report.pdf（3 页）+ 作业感受 PDF + AI 使用说明 PDF + 主表（README 内） | report.pdf（6 页，含主表与分阶段分析）、`router_fallbacks.jsonl` 逐请求路由日志 |

交付以 `ray-serve-4gpu/` 为准；`ray-serve-1gpu/` 保留作为单卡环境下的交叉验证（其 README
第 7 节说明了单卡与四卡的不可直接比较之处）。

> 这一步曾判断有误：本仓库早期 README 称「任务书只要求一个 HW2 zip」，据此删掉了
> HW3 的交付 zip。核对第三关任务书原文后已恢复：任务书明确要求在 github 上传
> `HW3-姓名（或学号）.zip` 且**解压后仅包含同名根目录**，现补齐并改为可脚本重建。
