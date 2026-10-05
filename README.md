# HW3-0102603133：比较并改进 Ray Serve 路由（挑战三）

## 1. 实验环境

| 项目 | 版本/配置 |
| --- | --- |
| GPU | 1 × 24GB（实验用 RTX 4090D；4 × GPU 亦可，见 launch 说明） |
| 操作系统 | Ubuntu 22.04 容器（SeetaCloud） |
| SGLang | **0.5.14**（`sglang[all]==0.5.14`，Python 3.12，sglang-env） |
| Ray | **2.56.0**（`ray[serve]==2.56.0`，Python 3.10，ray-env） |
| 模型 | Qwen/Qwen3-0.6B（`~/workspace/hw3/models/Qwen3-0.6B`） |
| 固定负载 | `26fall-HW-data/workloads/hw2/target3-routing-policies/`（SHA-256 见下） |

负载校验（必须通过，`run_round.sh` 会自动执行）：

```text
sha256: f154ba954e28ca9612257edf5deb0d5dfc6bf27fd0115a701e1f49e52df75b03
families: 64, warmups: 64, measured: 2048, planned_duration_s: 29.538768
```

## 2. 安装

```bash
cd HW3-0102603133/src/target3
bash setup_env.sh        # 建 sglang-env 与 ray-env 两个 conda 环境（国内镜像）
bash download_model.sh   # ModelScope 下载 Qwen3-0.6B（失败自动 fallback 到 HF_MIRROR）
```

负载目录默认在仓库内 `HW3-0102603133/workloads/target3-routing-policies/`；
若仓库中不含该目录（打包时已排除），请先
`git clone https://github.com/Zirkland/26fall-HW-data.git` 并
`export WORKLOAD_DIR=<克隆目录>/workloads/hw2/target3-routing-policies`。

## 3. 启动与回放（每组实验）

```bash
cd HW3-0102603133/src/target3
NUM_GPUS=1 bash launch_sglang.sh     # 启动 4 个 SGLang（端口 30000-30003）；4 卡机器用 NUM_GPUS=4

# 一键整链（推荐，A/B1/B2/C/D 顺序各跑一轮 run-1）
B_PICK=64 TIMEOUT_S=900 bash run_all_rounds.sh

# 或逐组：
bash run_round.sh A_default
bash run_round.sh B_cand1
bash run_round.sh B_cand2
B_PICK=64 bash run_round.sh C_affinity
B_PICK=64 bash run_round.sh D_improved

bash stop_all.sh   # 全部做完后停止 SGLang + Ray
```

- `B_PICK=64`：B 组两个候选中 64 同时具备更高吞吐与更低延迟（见 4.1 主表）。
- `TIMEOUT_S=900`：官方压测端默认单请求 300s；单卡 4 后端容量 < 到达率
  （≈69 req/s），组 A/C 的队列排空需 360~450s，300s 会人为截断
  （组 A 曾 130 条 `TimeoutError`）。B/D 的最大延迟远低于 300s，放宽超时不改变
  其结果，仅保证五组配置一致。每轮回放均覆盖 run-1 时传 `OVERWRITE=1`
  （`run_all_rounds.sh` 已内置）。
- `ulimit -n`：容器默认 1024。压测端 `TCPConnector(limit=0)` + 2048 并发连接会
  耗尽 fd（首轮 873/2048 条 `OSError(24) Too many open files`）。
  `run_round.sh` 已自动提升到硬上限（65535），无需手工设置。

`run_round.sh` 每轮自动完成：停止上一轮 Serve → 用本轮配置重新部署 →
`POST /flush_cache` 清空四个后端 → 官方 `run_workload.py` 先顺序跑 64 条预热、
再按到达时间回放 2048 条测量 → 校验退出状态与 `summary.json` → 拆掉 Serve。
结果写入 `results/target3/<组>/run-1/`（`config.json`、`warmups.csv`、
`requests.csv`、`summary.json`，外加 D 组的 `router_fallbacks.jsonl`）。

target1（前缀缓存测量）：

```bash
python src/target1/measure_prefix_cache.py \
    --base-url http://127.0.0.1:30000 --output-dir results/target1
```

汇总与主表：

```bash
# 官方多轮汇总（A/B1/B2/C/D）
python <WORKLOAD_DIR>/compare_runs.py --baseline A \
  --run A=results/target3/A_default/run-1/summary.json \
  --run B1=results/target3/B_candidates/candidate-1/run-1/summary.json \
  --run B2=results/target3/B_candidates/candidate-2/run-1/summary.json \
  --run C=results/target3/C_affinity/run-1/summary.json \
  --run D=results/target3/D_improved/run-1/summary.json \
  --output results/comparison.json

# 本包的报告主表（markdown，一页看清成功率/吞吐/命中率/prefill/TTFT p95/E2E p95/后端分布）
python src/target3/analyze.py \
  results/target3/A_default/run-1/summary.json \
  results/target3/B_candidates/candidate-1/run-1/summary.json \
  results/target3/B_candidates/candidate-2/run-1/summary.json \
  results/target3/C_affinity/run-1/summary.json \
  results/target3/D_improved/run-1/summary.json \
  | tee results/target3_main_table.md
```

## 4. 脚本用途

| 脚本 | 用途 |
| --- | --- |
| `src/target3/setup_env.sh` | 建 `sglang-env`（sglang[all]==0.5.14）与 `ray-env`（ray[serve]==2.56.0 + httpx + aiohttp），配国内镜像 |
| `src/target3/download_model.sh` | ModelScope 下载 Qwen3-0.6B（fallback：huggingface-cli + HF_MIRROR） |
| `src/target3/launch_sglang.sh` | 启动 4 个 SGLang（30000-30003）；`NUM_GPUS=1` 时四进程共享 GPU 0 并调小 `--mem-fraction-static`，`NUM_GPUS=4` 时每进程独占一卡；等待 `/v1/models` 就绪 |
| `src/target3/stop_all.sh` | 停 SGLang、serve_app.py、`ray stop` |
| `src/target3/serve_app.py` | **核心**：`ray.cluster_utils.Cluster` 建 1 head + 4 worker（含自定义资源 `hw3_worker`）；部署单个 `sglang-router`（`route_prefix="/"`，4 replicas，经 placement-group 落到 4 个不同 worker，每副本按 node id 固定转发一个 SGLang）；`ROUTER_MODE`（`--router-mode`）切换 A/B/C/D 的 `RequestRouterConfig`；`/generate` 的 SSE（含 `meta_info.cached_tokens`）原样回传，并设置 `X-Ray-Replica-ID` / `X-Ray-Node-ID` / `X-SGLang-Backend` 响应头；`GET /healthz` 供就绪检查 |
| `src/target3/routers.py` | **D 组**：`AffinityLoadAwareRouter`（继承 `ConsistentHashRouter`）：一致性哈希保证前缀亲和；若亲和副本的实时 in-flight 队列长度 ≥ 阈值（默认 75% × max_ongoing_requests），则改走当前最空闲副本；每次 fallback 记入 `$HW3_ROUTER_LOG`。只用当前请求（`X-Session-Id`）与当前服务状态（实时探测的队列长度），不读未来请求 |
| `src/target3/run_round.sh` | 单轮实验编排：提升 `ulimit -n` → 重部署 → flush_cache → 官方 `run_workload.py` 回放（`--timeout $TIMEOUT_S`）→ 校验 → 拆 Serve。**回放直接使用课程官方流量发生器** |
| `src/target3/run_all_rounds.sh` | 一键顺序跑 A/B1/B2/C/D 各一轮（`B_PICK=64`、`TIMEOUT_S=900`、`OVERWRITE=1`） |
| `src/target3/analyze.py` | 从官方 `summary.json` 生成报告主表（markdown） |
| `src/target3/common.py` | 百分位/统计/表格等小工具 |
| `src/target1/measure_prefix_cache.py` | **target1**：挑战二规范的前缀缓存两组对照测量（详见 `src/target1/README.md`） |

## 5. 架构说明（重要设计决策）

- **为什么是一个 deployment × 4 replicas，而不是 4 个 deployment？**
  课程要求 C 组使用 Ray Serve 内置的 `ConsistentHashRouter(num_fallback_replicas=0)`，
  D 组要求"在 RayServe 的扩展接口上完成改进"。这两个要求都指向
  `RequestRouterConfig(request_router_class=...)`，而该接口的作用域是**一个
  deployment 的多个 replicas 之间**的路由。因此 `sglang-router` 是一个
  deployment、4 个 replicas，每个 replica 固定转发一个 SGLang 后端；
  "Ray Serve 负责选择 Replica"由可配置的 router 实现，A/B/C/D 的差异只在
  `RequestRouterConfig` 与 `max_ongoing_requests`。
- **副本如何固定到不同 worker？** 4 个 worker 节点各带自定义资源
  `hw3_worker=1`；deployment 的 placement-group bundle 为
  `{"CPU": 1, "hw3_worker": 1}`，每 worker 恰能容纳一个副本。
- **副本如何知道自己该转发哪个 SGLang？** `serve_app.py` 在部署前用
  `ray.nodes()` 拿到 4 个 worker 的 node id，按排序映射到后端 0-3，
  以构造参数传入；副本启动时用 `ray.get_runtime_context().get_node_id()`
  查表。
- **缓存命中率从哪来？** SGLang `/generate` 流式响应的
  `meta_info.cached_tokens`（v0.5.14 `tokenizer_manager.py` 写入）；
  Serve 层原样透传 SSE，官方 `run_workload.py` 从首个 chunk 提取并汇总为
  `cache_hit_rate = cached / prompt`。无需另查 `/metrics`。

## 6. 结果目录与报告表格对应关系

| 结果目录 | 报告主表行 |
| --- | --- |
| `results/target3/A_default/run-1/` | A（p2c，max_ongoing=5） |
| `results/target3/B_candidates/candidate-1/run-1/` | B 候选 1（p2c，max_ongoing=16） |
| `results/target3/B_candidates/candidate-2/run-1/` | B 候选 2（p2c，max_ongoing=64） |
| `results/target3/C_affinity/run-1/` | C（consistent_hash，max_ongoing=64） |
| `results/target3/D_improved/run-1/` | D（affinity_load_aware，max_ongoing=64，附 `router_fallbacks.jsonl`，仅含本轮数据） |
| `results/target1/shared_prefix/run-1/` | target1 共享前缀组（32 条 + 1 条预热） |
| `results/target1/dispersed_prefix/run-1/` | target1 分散前缀组（32 条） |
| `results/target3_main_table.md` | `analyze.py` 生成的报告主表原文 |

`analyze.py` 输出的列即报告主表的列：成功率、吞吐量、缓存命中率、
实际 Prefill token 数、TTFT p50/p95、端到端延迟 p95、四后端请求分布；
`traffic_phases`（steady/burst/recovery）与 `popularity_tiers` 用于正文分析。

**最终运行（2026-10-05，run-1）五组均为 2048/2048 全部成功**，与 report.pdf
主表一一对应。

## 7. 已知限制与与作业说明的偏差

- 单 GPU（`NUM_GPUS=1`）时 4 个 SGLang 共享 24GB 显存，各
  `--mem-fraction-static=0.18`、`--attention-backend triton --disable-cuda-graph`；
  KV 池较小，burst 阶段出现排队，但不影响正确性。4 卡时用 `NUM_GPUS=4` + 0.85。
- 与作业说明的偏差：说明假设每组预约 4 张 GPU，本次实际为 1 张 4090D 上运行 4 个 SGLang 后端（NUM_GPUS=1，四进程共享 GPU 0，--mem-fraction-static=0.18）。四组的负载、模型、后端数量与路由实现以外的参数完全一致，因此 A/B/C/D 之间的横向对比成立；但单卡 KV 池更小，绝对吞吐与延迟数值不能与 4 卡环境的队伍直接比较。脚本保留了 NUM_GPUS=4 的路径，具备 4 卡时可原样复跑。
- 压测端 `ulimit -n` 与单请求超时两处客户端配置按上文说明统一调整；
  `run_round.sh` 内已有注释与自动处理。
- D 组路由器的队列长度探测是 RPC，会给每个路由决策增加少量延迟；
  这是"负载感知"的代价，报告 4.4 节已如实讨论。
