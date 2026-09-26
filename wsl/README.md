# SGLang 在线推理挑战 —— WSL 侧执行说明

## 依赖的大文件已全部预取完毕（无需 WSL 访问 GitHub / HuggingFace）

| 文件 | 位置 | 用途 |
|---|---|---|
| `mooncake_trace.jsonl` | `D:\first-task\work\data\` | Mooncake FAST'25 trace |
| `sglang-v0.5.14.tar.gz` | `D:\first-task\work\data\` | SGLang 0.5.14 源码快照 |
| `cpython-3.12-linux-x86_64.tar.gz` | `D:\first-task\work\data\` | standalone CPython 3.12 |
| `Qwen3-0.6B/`（含 model.safetensors，1.5 GB） | `D:\first-task\work\models\` | 模型权重 |

脚本会**优先使用本地文件**，只有在本地文件缺失时才回退到网络下载，
因此即使 WSL 内 `github.com` 被代理劫持也不影响流程。

## 一键执行（在 WSL 终端里）

```bash
# 推荐：以 root 执行，避免 apt 交互式密码提示
sudo bash /mnt/d/first-task/wsl/run_all.sh
```

或在 Windows 侧（若 `wsl.exe` 未被安全策略禁用）：

```powershell
wsl -u root -e bash /mnt/d/first-task/wsl/run_all.sh
```

分步执行：

```bash
sudo bash /mnt/d/first-task/wsl/01_setup_env.sh   # 造环境（编译 sgl-kernel，最耗时）
sudo bash /mnt/d/first-task/wsl/02_start_server.sh # 起 Ray + SGLang 服务
sudo bash /mnt/d/first-task/wsl/03_single_request.sh # 截图1 的原始证据
sudo bash /mnt/d/first-task/wsl/06_make_shots.sh   # 汇编截图文本

# 截图2：Mooncake 采样 + Poisson 压测
# 注意：04_benchmark.py 是 Python，必须用 SGLang 环境的解释器执行，不能用 bash
source /mnt/d/first-task/work/env.sh
$VENV/bin/python /mnt/d/first-task/wsl/04_benchmark.py \
    --n 20 --mean-interval 2.0 --input-cap 1024 --out-cap 64
```

## 脚本职责

| 脚本 | 作用 |
|---|---|
| `00_common.sh` | 版本、路径、日志、apt/LD_PRELOAD/下载、PATH、CPU 指令集探测等公共函数 |
| `01_setup_env.sh` | apt 依赖 → uv → CPython 3.12 → SGLang 0.5.14 CPU 编译 → sgl-kernel CPU 编译 → Ray 2.56.0 独立环境 → 模型就位 |
| `02_start_server.sh` | 启动 Ray head；以 `--device cpu --tp 1` 启动 OpenAI-compatible 服务并等待就绪 |
| `03_single_request.sh` | `GET /v1/models` + 一次完整推理（含流式），原始输出落盘 |
| `04_benchmark.py` | Mooncake trace 采样 + Poisson 到达压测，记录 input/output tokens、status、TTFT、latency |
| `05_patch_cpu_isa.sh` | **无 AVX-512 时的自救补丁**：改写 sgl-kernel 的 ISA 编译选项并重编译（详见下节） |
| `06_make_shots.sh` | 从真实日志汇编截图文本（截图1 / 截图2a / 截图2b） |
| `99_selfcheck.sh` | 环境自检：torch / sgl_kernel / sglang 能否导入 |
| `run_all.sh` | 串联全流程，日志汇总到 `work/logs/run_all.log` |

## ⚠️ 关键坑：sgl-kernel 的 CPU 后端硬性要求 AVX-512

这是本次部署中最容易踩、且报错信息最不直观的一个问题。

**现象**：源码编译全部成功，但一执行 `import sgl_kernel` 就崩溃，报
`Illegal instruction (core dumped)`，Python 层看不到任何异常栈。

**根因**（已在源码中核实）：`sgl-kernel/csrc/cpu/CMakeLists.txt` 对**所有** x86_64
目标无条件加入

```
-march=x86-64-v4  -mavx512bf16  -mavx512vnni  -mamx-tile  -mamx-bf16  -mamx-int8
```

而 `csrc/cpu/vec.h` 的前 5 行据此推导：

```c
#if defined(__AVX512F__) && defined(__AVX512BF16__) && defined(__AMX_BF16__)
#define CPU_CAPABILITY_AVX512
#endif
```

也就是说，**编译期就把整个 `common_ops.so` 绑定到了 AVX-512 + AMX**，
且没有任何运行时指令集分派（官方 `docker/xeon.Dockerfile` 面向的是
Intel Xeon Sapphire Rapids 及以上）。实测该 `.so` 中含 98,672 处 `zmm`
（AVX-512）寄存器引用。

因此，在**无 AVX-512 的消费级 x86_64 CPU**（如 Intel Core Ultra / Alder Lake /
Raptor Lake、AMD Zen 1~3）上，二进制必然 SIGILL。

**解决**：改以 AVX2 基线（`-march=x86-64-v3`）编译。此时 `__AVX512F__` 不再定义，
`CPU_CAPABILITY_AVX512` 自动失效，源码中所有 `#if defined(CPU_CAPABILITY_AVX512)`
的加速段被跳过，落到 `vec.h` 里已有的通用回退实现（例如
`vec_reduce_sum/max` 的 `#else` 分支）。

`05_patch_cpu_isa.sh` 正是做这件事，且：

- 补丁是**增量**的（保留上游分支，仅在 `SGLANG_CPU_ISA=baseline` 时切换），原文件备份为
  `CMakeLists.txt.orig`，可随时回退；
- `01_setup_env.sh` 会通过 `/proc/cpuinfo` **自动探测 AVX-512**，无则自动调用该补丁，
  有则保持上游 v4 编译，无需人工判断。

**代价**：AVX2 基线下，少量依赖 AVX-512/AMX 的量化 GEMM（fp8 / int4 / int8）与
VNNI 优路径不可用，走通用实现，绝对吞吐低于 Xeon。但 bf16/fp32 的正常推理路径完整可用。

## 产物位置

```
D:\first-task\work\
├── logs\      run_all.log / sglang_server.log / ray_start.log / 00_env_report.log
├── results\   shot1_raw.txt / benchmark_results.{json,csv} / sglang_metrics.txt
└── data\      mooncake_trace.jsonl
```

## 关键设计说明

- **SGLang 与 Ray 分属两个 venv**（`$VENV` / `$RAYVENV`），符合题目「可放在不同 Python 环境、通过 HTTP 通信」的要求。
- **CPU 引擎**：`SGLANG_USE_CPU_ENGINE=1`，并逐库探测拼装 `LD_PRELOAD`（tcmalloc / tbbmalloc / libiomp5），不硬编码库名。
- **前缀复用**：所有压测请求共享 **256** token 公共前缀（对应 trace 中共享的 `hash_ids[0]`），用于真实触发 RadixCache。
  脚本 `--prefix-tokens` 默认 512，但会按 `P = min(prefix_tokens, max_input_tokens // 4)` 夹紧；
  本次 `--input-cap 1024` 下实际生效值为 **256**（与 `benchmark_results.json` 的 `shared_prefix_tokens` 一致）。
- **绕开系统代理**：所有对 `127.0.0.1` 的请求均使用 `--noproxy '*'` 或 `http.client` 直连，
  避免 Watt Toolkit 之类的代理拦截本地回环。
- **换行符**：所有 `.sh` 均为 LF，已在仓库中通过 `.gitattributes` 固化，避免 `bad interpreter: ^M`。
