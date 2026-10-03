# HW2 — SGLang 前缀缓存测量 与 /generate 请求流程分析

> 第二次挑战作业。承接第一次挑战（SGLang 0.5.14 在线推理服务在 WSL2 纯 CPU 上的部署与压测），
> 本次完成两件事：**任务一**测量前缀缓存（Radix Cache）的真实效果；**任务二**沿指定主线阅读
> SGLang v0.5.14 源码，追踪一条 `/generate` 请求的完整生命周期。

---

## 1. 运行环境

| 项 | 值 |
|---|---|
| 宿主 | Windows + WSL2 |
| 发行版 | Ubuntu 26.04 LTS (Resolute Racoon) |
| CPU | Intel Core Ultra 5 338H（代号 Panther Lake），**12 vCPU**，无 AVX-512 / 无 AMX |
| 内存 | 15 GiB（宿主 31.5 GB 板载 LPDDR5X） |
| 核显 | Intel Arc B370（核显）＋ NPU。**未参与计算**：WSL 内缺 Intel 计算运行时（Level-Zero / OpenCL / SYCL），`/dev/dri` 仅由内核 `vgem` 虚拟桩提供，无 `i915`/`xe` DRM 驱动。详见第一次挑战的 `evidence/10_gpu_probe.txt`、`11_gpu_probe_sudo.txt` |
| Python | 3.12.14（standalone，与发行版自带的 3.14 解耦） |
| **SGLang** | **0.5.14**（源码构建，`--device cpu`，`--attention-backend torch_native`） |
| **Ray** | **2.56.0**（独立 venv，与 SGLang 通过 HTTP 通信） |
| **模型** | **Qwen/Qwen3-0.6B**（bf16） |
| torch | 2.12.0+cpu |
| 服务地址 | `http://127.0.0.1:30000` |

> …其中 CPU 上跑 0.5.14 需要一处**上游补丁**：`sgl-kernel/csrc/cpu/CMakeLists.txt` 对所有
> x86_64 无条件加 `-march=x86-64-v4 -mavx512* -mamx-*`，在没有 AVX-512 的消费级 CPU 上
> `import sgl_kernel` 必然 `Illegal instruction`。`src/env/05_patch_cpu_isa.sh` 把它改到
> AVX2 基线（`-march=x86-64-v3`）。完整定位过程见第一次挑战仓库。

---

## 2. 安装方法

环境（编译 `sgl-kernel` 最耗时，约 20–40 分钟）由 `src/env/` 下的脚本一键构建，**幂等、可重复执行**：

```bash
# 在 WSL 内（建议 root，避免 apt 交互式密码提示）
cd /mnt/d/<你的路径>/HW2-林彦超
sudo bash src/env/01_setup_env.sh
```

`01_setup_env.sh` 会自动：探测 AVX-512 → 无则打 ISA 补丁 → 解压本地预取的 CPython / SGLang 源码 /
模型权重（**全程离线，不需要访问 GitHub / HuggingFace**）→ 建两个隔离 venv → 编译 → 写出
`/mnt/d/first-task/work/env.sh`（后续脚本都 source 它）。

> 大文件预取脚本见第一次挑战的 `tools/fetch_all.py`；本目录的 `src/env/` 与那份脚本配套，
> 若本地尚无预取物，请先跑预取。

---

## 3. 启动与回放命令

```bash
# 0) 载入环境变量
source /mnt/d/first-task/work/env.sh

# 1) 启动 Ray head + SGLang 服务（Radix Cache 默认开启，无需额外开关）
sudo bash src/env/02_start_server.sh
#    就绪判据：curl -s --noproxy '*' http://127.0.0.1:30000/v1/models | grep '"id"'

# 2) 任务一：两组各 32 条测量（顺序 shared → dispersed）
sudo bash src/target1/run_target1.sh run-1 shared,dispersed

# 3) 任务一：交换顺序再跑一次，用于排除执行顺序带来的系统性偏差
sudo bash src/target1/run_target1.sh run-2 dispersed,shared

# 4) 任务二：重新生成流程图（可选，仓库内已含生成物 flowchart.svg）
python src/target2/make_flowchart.py src/report_src

# 5) 由 results/ 的原始结果生成报告 HTML，再用 Chrome 无头模式渲染 PDF
python src/report_src/make_report.py
```

`run_target1.sh` 也接受环境变量覆盖：`WORK`（工作根目录）、`SGL_PORT`、`SGL_HOST`。

---

## 4. 脚本用途

| 路径 | 用途 |
|---|---|
| `src/env/00_common.sh` | 公共配置与工具函数（版本、路径、日志、`LD_PRELOAD` 逐库探测、CPU 指令集探测、`wait_ready`） |
| `src/env/01_setup_env.sh` | 造环境：apt 依赖 → uv → CPython 3.12 → SGLang 0.5.14 CPU 编译 → sgl-kernel 编译 → Ray 2.56.0 → 模型就位 |
| `src/env/02_start_server.sh` | 启动 Ray head 与 SGLang OpenAI-compatible 服务，并等待就绪 |
| `src/env/05_patch_cpu_isa.sh` | **无 AVX-512 时的自救补丁**：把 sgl-kernel 的 CPU 后端从 x86-64-v4 降到 AVX2 基线并重编译 |
| `src/target1/prefix_cache_bench.py` | **任务一主程序**：构造两组负载 → 组前 `flush_cache` → 共享前缀组额外预热 → 并发 8 发 32 条流式 `/generate` 请求 → 采集逐请求指标与汇总 |
| `src/target1/run_target1.sh` | 任务一一键运行器（确保服务在线 + 记录版本与缓存配置 + 调用主程序） |
| `src/target2/make_flowchart.py` | **任务二流程图生成器**，输出 `src/report_src/flowchart.svg` |
| `src/report_src/make_report.py` | 读 `results/` 下的原始结果，生成 `report.html`（再由 Chrome 渲染成 `report.pdf`） |
| `src/report_src/*.html` | 报告与 AI 使用说明的 HTML 源（可复现） |

### 任务一主程序的关键参数

| 参数 | 值 | 依据 |
|---|---|---|
| `--n` | 32 | 任务书：每组 32 条测量请求 |
| `--concurrency` | 8 | 任务书：最大并发数为 8 |
| `--prefix-tokens` / `--suffix-tokens` | 2048 / 64 | 任务书表格：2048 共享前缀 + 64 独立后缀 |
| 采样参数 | `temperature=0, max_new_tokens=16, ignore_eos=true, sampling_seed=2026` | 任务书硬性要求，写在 `SAMPLING` 常量里 |
| `--tag` | `run-1` / `run-2` | 同一配置多次实验，分别落到不同子目录 |

---

## 5. 结果目录与报告表格的对应关系

目录结构按任务书规定组织：`run-1/`、`run-2/` 这类「同一配置的多次实验」子目录建在
`shared_prefix/`、`dispersed_prefix/` **之下**。

```
results/
└── target1/
    ├── shared_prefix/                     # 共享前缀组（2048 共享前缀 + 64 独立后缀）
    │   ├── run-1/
    │   │   ├── version_info.log           # 软件版本 / CPU / 服务端 KV 配置 → 报告「实验环境」表
    │   │   ├── run_meta.json              # 本次运行的配置与负载设计（运行级，两组各存一份）
    │   │   ├── run_summary.json           # 两组汇总的合并视图（运行级，两组各存一份）
    │   │   ├── service_warmup.json        # 首次实验前的短请求预热（不计入结果）
    │   │   ├── flush_cache.json           # 组前 POST /flush_cache 的响应（含 success）★
    │   │   ├── warmup_request.json        # 本组的 1 条预热请求（不计入结果）
    │   │   ├── requests.jsonl             # 32 条测量请求的逐请求原始记录 ★
    │   │   ├── summary.json               # 本组汇总指标（报告主表的数据源）★
    │   │   └── server_log_slice.log       # 本组时间窗内的服务端日志（Prefill batch 行）★
    │   └── run-2/                         # 交换两组顺序，用于稳健性检查
    └── dispersed_prefix/                  # 分散前缀组（首 token 两两不同，前缀不可复用）
        ├── run-1/                         # 内容同 shared_prefix/run-1/，但无 warmup_request.json
        └── run-2/
```

**报告主表 ↔ 原始结果的对应**：

| 报告主表的行 | 取自 `results/target1/<组>/run-N/` |
|---|---|
| 成功率 | `summary.json` → `n_success` / `n_requested`（明细见 `requests.jsonl` 的 `ok`） |
| 吞吐量 | `summary.json` → `output_throughput_tok_s`（= Σ`completion_tokens` / `wall_clock_s`） |
| 缓存命中率 | `summary.json` → `cache_hit_rate`（= Σ`cached_tokens` / Σ`prompt_tokens`，两项均取自服务端 `meta_info`） |
| 实际 Prefill token 数 | `summary.json` → `actual_prefill_tokens`（= Σ`prompt_tokens` − Σ`cached_tokens`） |
| TTFT / TPOT / 端到端 p50、p95 | `summary.json` → `ttft_ms` / `tpot_ms` / `e2e_ms` 的 `p50`、`p95` |
| 逐请求明细（附录/散点） | `requests.jsonl` 每行一条：`ttft_ms`、`tpot_ms`、`e2e_ms`、`prompt_tokens`、`cached_tokens` |
| 6.3 节的「准入等待」证据 | `server_log_slice.log` 的前两条 `Prefill batch` 行（`#queue-req` 与两条记录的时间差）+ `requests.jsonl` 的轮内端到端极差 |
| 「服务端确实发生前缀复用」的旁证 | `server_log_slice.log` 中的 `Prefill batch, ..., #cached-token: N` |

`summary.json` 里的 `cache_hit_rate` 与 `actual_prefill_tokens` **全部来自服务端返回的
`meta_info.prompt_tokens` / `meta_info.cached_tokens`**，不是客户端按输入长度估算的，
因此可以直接与 `server_log_slice.log` 的 `#cached-token` 互相印证。

---

## 6. 一致性与已知现象说明

- 所有指标、日志与图表**均取自真实运行过程**，未做人工改写或美化。
- 两组负载的控制变量：**除「前缀能否复用」外全部对齐**——
  输入长度同为 2112、独立后缀逐 token 相同、请求顺序与并发数相同、采样参数相同。
  分散前缀组通过「把位置 0 换成两两互不相同的 token」破坏前缀共享，
  其余 2047 个共享区 token 与共享前缀组逐位相同（且这 32 个 token 均不落在共享前缀内）。
  构造逻辑与断言见 `prefix_cache_bench.py` 的 `build_workloads()`。
- **TTFT / TPOT 的读数需要谨慎**：同一轮的 8 条请求在服务端同批同步推进，端到端耗时几乎相等，
  因此 TTFT 与 TPOT 是「同一段固定时长在等待与解码窗口之间的分配」，二者此消彼长。
  跨组比较应以端到端时长与吞吐为准。详见 `report.pdf` 的 6.1 节。
- **准入等待（实测现象）**：纯 CPU 单进程部署下，HTTP 接收路径与「调度 + 前向计算」串行，
  一次长前向期间新到的请求无法被及时读取。服务端日志显示每一轮只有 1 条请求先被准入
  （`#queue-req: 0`），其余 7 条约 12 s 后才整批进入。该现象**对两组同等存在**，
  故跨组的相对差异仍然可信；而缓存命中率、实际 Prefill token 数取自服务端计数器，
  完全不受时序影响。详见 `report.pdf` 的 6.3 节。
- 本机为纯 CPU 推理（12 vCPU），`max_new_tokens=16` 下单请求端到端在数十秒级，
  因此两组各 32 条请求的测量需要数分钟；这是硬件条件决定的，不是程序问题。
- 所有 `.sh` / `.py` 均为 **LF 换行**。
