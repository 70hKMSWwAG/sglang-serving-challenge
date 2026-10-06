# HW3：比较并改进 Ray Serve 路由

四副本 SGLang + Ray Serve 路由对照实验（A / B1 / B2 / C / D 五轮）。拓扑：
`Client -> Ray Serve HTTP Proxy(:8000) -> Replica 0..3（各在独立 worker 逻辑节点）-> SGLang 0..3（GPU 0..3）`。
目标一（前缀缓存测量）的脚本与结果在 `src/target1/` 与 `results/target1/`。

## GPU 与软件版本

- GPU：4 × NVIDIA GeForce RTX 4090 D（24 GB），单机，驱动 580.105.08，CUDA 13.0（AutoDL/SeetaCloud 北京 B2 区）
- SGLang 后端环境：`/root/autodl-tmp/envs/sgl`（Python 3.11）
  - `sglang[all]==0.5.14`，`torch==2.11.0+cu130`，`transformers==5.8.1`，`ninja`
- Ray Serve 环境：`/root/autodl-tmp/envs/rayenv`（Python 3.11）
  - `ray[serve]==2.56.0`，`protobuf==6.33.5`（7.x 与 Ray 2.56 不兼容，见文末排错记录），`httpx`，`aiohttp`
- 模型：`Qwen/Qwen3-0.6B`，本地路径 `/root/autodl-tmp/models/Qwen3-0.6B`（hf-mirror 下载）
- 两个环境互相独立，只通过 HTTP 通信；SGLang 后端监听 31000–31003，Ray Serve 代理监听 8000

## 安装方法

```bash
# pip 源（AutoDL 默认的阿里云源仅 0.2–0.6 MB/s，换清华源后约 16 MB/s）
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 1) SGLang 后端环境（venv 或 conda 均可）
python -m venv /root/autodl-tmp/envs/sgl
/root/autodl-tmp/envs/sgl/bin/pip install ninja
/root/autodl-tmp/envs/sgl/bin/pip install "sglang[all]==0.5.14" "torch==2.11.0" "transformers==5.8.1"

# 2) Ray Serve 环境
python -m venv /root/autodl-tmp/envs/rayenv
/root/autodl-tmp/envs/rayenv/bin/pip install "ray[serve]==2.56.0" "protobuf==6.33.5" httpx aiohttp

# 3) 模型（国内走 hf-mirror）
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download Qwen/Qwen3-0.6B \
  --local-dir /root/autodl-tmp/models/Qwen3-0.6B

# 4) 课程固定负载（负载 jsonl 由课程仓库发布，不要改动）
git clone https://github.com/Zirkland/26fall-HW-data.git
export COURSE_DIR=$PWD/26fall-HW-data/workloads/hw2/target3-routing-policies
python -m pip install -r "$COURSE_DIR/requirements.txt"
```

`src/target3/course_workload/` 里附带了课程负载脚本的**原样拷贝**（见其 NOTICE.md），
离线时可直接把 `COURSE_DIR` 指向它，但负载 jsonl 仍需自行下载。

## 启动与回放命令

所有脚本在 `src/target3/` 下运行。`RAY_PY`、`SGL_PY`、`MODEL` 三个环境变量按上面的路径设置
（脚本内已有同款默认值，路径一致时无需显式 export）。

```bash
export COURSE_DIR=/root/autodl-tmp/hw3/26fall-HW-data/workloads/hw2/target3-routing-policies
cd src/target3

./launch_backends.sh        # 启动 4 个 SGLang 后端（GPU 0-3，端口 31000-31003），等 /v1/models 就绪
./run_all.sh                # 一口气跑 A、B1、B2、C、D 五轮
./stop_backends.sh          # 收尾
```

或分轮执行（每轮自动完成：停掉旧 Ray 集群 -> 重建 1 head + 4 worker -> 部署 Replica -> flush 四个后端缓存 -> 回放固定负载）：

```bash
./run_group.sh A  A_default      results/target3/A_default
./run_group.sh B1 B1_candidate_1 results/target3/B_candidates/candidate-1
./run_group.sh B2 B2_candidate_2 results/target3/B_candidates/candidate-2
B_MAX_ONGOING=16 ./run_group.sh C  C_affinity  results/target3/C_affinity
B_MAX_ONGOING=16 ./run_group.sh D  D_improved  results/target3/D_improved
```

> B 的选定值为 **16**（依据见 report.pdf §3.1），因此跑 C、D 前设置 `B_MAX_ONGOING=16`。

五轮的配置（`deploy_app.py` 与 `run_workload.py` 记录一致）：

| 组别 | 路由器 | max_ongoing_requests | 说明 |
| --- | --- | ---: | --- |
| A | p2c（Ray 默认请求路由器） | 5 | Ray Serve 默认值 |
| B1 | p2c | 16 | B 候选 1 |
| B2 | p2c | 32 | B 候选 2 |
| C | consistent_hash（num_fallback_replicas=0） | 16 | 按 X-Session-Id 严格亲和，观察缓存收益与热点 |
| D | affinity_load（自研，`src/target3/routers.py`） | 16 | 前缀亲和优先 + 负载感知降级 |

## 脚本用途

| 脚本 | 作用 |
| --- | --- |
| `launch_backends.sh` | 每张 GPU 启动 1 个 SGLang 0.5.14 后端（端口 31000–31003），轮询 /v1/models 直至就绪 |
| `flush_backends.py` | 对四个后端 POST /flush_cache 并确认成功（每轮开始前调用；0.5.14 返回纯文本） |
| `deploy_app.py` | 用 `ray.cluster_utils.Cluster` 建 1 head + 4 worker 逻辑节点，按组部署 4 个 Replica 并绑定 replica_slot 资源 |
| `sglang_replica.py` | Replica：流式转发 /generate 到固定 SGLang 后端，回写路由响应头；异步上报在飞数 |
| `routers.py` | 组 D 路由器 AffinityLoadAwareRouter：blake2b 稳定哈希选首选副本，在飞数 ≥ 0.5×上限时把「最空闲副本 + 首选副本」放进同一优先级让 Serve 择优 |
| `run_group.sh` | 单轮编排：ray stop -> deploy_app.py -> flush_backends.py -> run_workload.py |
| `run_all.sh` | 五轮全跑：先 validate_workload.py 校验负载，再依次 A/B1/B2/C/D |
| `make_main_table.py` | 从各轮 summary.json 汇总生成 `results/target3/main_table.csv` |
| `course_workload/` | 课程负载脚本原样拷贝（run_workload.py / validate_workload.py / requirements.txt / NOTICE.md） |

目标一（第二关挑战任务一）：

| 脚本 | 作用 |
| --- | --- |
| `src/target1/measure_prefix_cache.py` | 共享前缀 vs 分散前缀对照测量（各 32 条、并发 8、temperature=0、max_new_tokens=16、ignore_eos=true、sampling_seed=2026），输出 requests.csv / summary.json / compare.json |

## 结果目录与报告表格的对应关系

```text
results/
├── target1/                          -> report.pdf §2「目标一」表格与图
│   ├── shared_prefix/                -> 共享前缀组（requests.csv, summary.json）
│   ├── dispersed_prefix/             -> 分散前缀组（requests.csv, summary.json）
│   └── compare.json                  -> 两组对照汇总
└── target3/
    ├── A_default/                    -> 报告主表 A 行（config.json, warmups.csv, requests.csv, summary.json）
    ├── B_candidates/
    │   ├── candidate-1/              -> 主表 B1 行（p2c, 16）
    │   └── candidate-2/              -> 主表 B2 行（p2c, 32）
    ├── C_affinity/                   -> 主表 C 行（consistent_hash）
    ├── D_improved/                   -> 主表 D 行（affinity_load）
    ├── main_table.csv                -> 报告主表（make_main_table.py 生成）
    └── comparison.json               -> 以 A 为基线的相对变化
```

- 主表各列（成功率、吞吐、缓存命中率、实际 prefill tokens、TTFT p50/p95、端到端 p95、后端分布）直接读自各轮
  `summary.json` 的 `schema_version=2` 字段；逐请求明细在 `requests.csv`，分阶段（steady/burst/recovery）
  指标在 `summary.json` 的分阶段字段。
- 主表生成：`make_main_table.py results/target3`；相对变化（课程脚本）：

```bash
python "$COURSE_DIR/compare_runs.py" --baseline A \
  --run A=results/target3/A_default/summary.json \
  --run B1=results/target3/B_candidates/candidate-1/summary.json \
  --run B2=results/target3/B_candidates/candidate-2/summary.json \
  --run C=results/target3/C_affinity/summary.json \
  --run D=results/target3/D_improved/summary.json \
  --output results/target3/comparison.json
```

## 排错记录（组 D 从 5 req/s 到 63 req/s）

组 D 首跑出现 405/2048 请求失败、吞吐 5.03 req/s、TTFT p95 ≈ 107 s。逐层定位后确认三个叠加原因：

1. `choose_replicas()` 返回了多 rank（`[[冷副本...], [首选副本]]`）。Ray Serve 把多 rank 当作顺序重试，
   冷副本探测失败后再试首选副本，人为放大排队。改为单 rank 返回「最空闲副本 + 首选副本」二选一。
2. `record_routing_stats` 是同步方法，在高并发下阻塞 Replica 的 asyncio 事件循环，导致代理侧
   读队列长度超时。改为 `async def`。
3. **根因**：自定义路由器只继承了 `RequestRouter`，而 Ray 内置 p2c 的继承链是
   `FIFOMixin, LocalityMixin, MultiplexMixin, RequestRouter`。缺了 `FIFOMixin` 就丢失内置的
   FIFO 排队语义，2048 条高并发下路由任务退化。补上 `FIFOMixin` 后立即恢复：
   2048/2048 成功、62.99 req/s、TTFT p95 5.93 s。

环境层面另有两个坑，记录在此避免复踩：

- Ray 2.56 与 protobuf 7.x 不兼容（`FieldDescriptor ... no attribute 'label'`），4.25.x 又会拉出依赖冲突；
  `protobuf==6.33.5` 两者兼顾。
- Ray 2.56 的 `serve.run()` 已移除 `host/port` 参数；SGLang 0.5.14 的 `/flush_cache` 返回纯文本而非 JSON。
