# SGLang 在线推理服务挑战 —— 部署、验证与 Mooncake Trace 压测

在**纯 CPU、无 GPU** 的 WSL2 环境中，从源码构建 **SGLang 0.5.14** 并启动
OpenAI-compatible 在线推理服务，使用 **Qwen/Qwen3-0.6B**，随后以
**Mooncake FAST'25 trace** 采样构造 **泊松到达** 负载完成性能测试。

> **一句话结论**：任务已完成，服务正常在线推理，压测 20/20 全部成功。
> 但过程中遇到一个**上游代码的硬性限制**——SGLang 0.5.14 的 CPU 后端事实上要求
> AVX-512 + AMX，在没有 AVX-512 的消费级 CPU 上必然崩溃。本仓库包含该问题的
> **完整定位过程与可回退的修复补丁**。

---

## 1. 交付物（`deliverables/`）

| 文件 | 页数 | 内容 |
|---|---|---|
| `流程图.pdf` | 1 | 一次请求经过 SGLang 的完整流程（含 RadixCache / 调度 / KV Cache 环节） |
| `重点回答.pdf` | 1 | RadixAttention 原理、page-sized KV cache 与 prefix reuse 的层次关系、与 vLLM PagedAttention 的联系与差异 |
| `阅读文献笔记.pdf` | 2 | SGLang (NeurIPS'24) 与 vLLM (SOSP'23) 论文笔记 |
| `操作保存.pdf` | 4 | 服务启动与在线验证（截图1）、Mooncake 压测（截图2a/2b）、服务端前缀复用证据（附录） |
| `作业感受.pdf` | 2 | 完成过程、最困难的部分与克服方式、对 0→1 科研的体会 |
| `AI使用说明情况.pdf` | 2 | 所用模型、提示词、AI 的帮助方式、以及 AI 实际误导过我的地方 |

---

## 2. 运行环境

| 项 | 值 |
|---|---|
| 宿主 | Windows + WSL2 (Kernel 6.18.33.2) |
| 发行版 | Ubuntu 26.04.1 LTS (Resolute Racoon) |
| CPU | Intel Core Ultra 5 338H，**12 vCPU**（1 thread/core，1 NUMA node，**无 AVX-512 / 无 AMX**） |
| 内存 | 15 GiB |
| GPU | **无** |
| Python | 3.12.14（standalone，与发行版自带的 3.14 解耦） |
| 关键版本 | SGLang **0.5.14** · Ray **2.56.0** · torch 2.12.0+cpu · transformers 5.8.1 |

---

## 3. ⚠️ 核心问题：sgl-kernel 的 CPU 后端硬性要求 AVX-512

这是本次任务中最关键、也最难定位的一个问题，单独说明如下。

### 现象

源码全部编译成功（包括 `sgl-kernel` 的 C++ 扩展），但一执行：

```bash
python -c "import sgl_kernel"
```

进程直接 **`Illegal instruction (core dumped)`**，Python 层**看不到任何异常栈**。

### 根因

`SGLang v0.5.14` 的 `sgl-kernel/csrc/cpu/CMakeLists.txt` 对**所有** x86_64 目标无条件加入：

```
-march=x86-64-v4  -mavx512bf16  -mavx512vnni  -mamx-tile  -mamx-bf16  -mamx-int8
```

而 `csrc/cpu/vec.h` 的前 5 行据此推导：

```c
#if defined(__AVX512F__) && defined(__AVX512BF16__) && defined(__AMX_BF16__)
#define CPU_CAPABILITY_AVX512
#endif
```

也就是说，**编译期整个 `common_ops.so` 就被绑定到 AVX-512 + AMX**，
且没有任何运行时指令集分派。实测该 `.so` 中包含
**98,672 处 `zmm`（AVX-512）寄存器引用**。官方的
`docker/xeon.Dockerfile` 也印证：这个"CPU 后端"面向的是
Intel Xeon（Sapphire Rapids 及以上）。

因此，在**无 AVX-512 的 x86_64 CPU**（Intel Core Ultra / Alder Lake / Raptor Lake、
AMD Zen 1~3 等）上，二进制必然 SIGILL。

### 修复

改以 **AVX2 基线**（`-march=x86-64-v3`）编译。此时 `__AVX512F__` 不再定义，
`CPU_CAPABILITY_AVX512` 自动失效，源码中所有
`#if defined(CPU_CAPABILITY_AVX512)` 的加速段被跳过，落到 `vec.h` 里
**已有的通用回退实现**（例如 `vec_reduce_sum/max` 的 `#else` 分支）。

补丁见 `wsl/05_patch_cpu_isa.sh`，特点：

- **增量**：保留上游 `v4` 分支，仅在 `SGLANG_CPU_ISA=baseline` 时切换到 AVX2；
- **可回退**：原文件备份为 `CMakeLists.txt.orig`；
- **自动**：`01_setup_env.sh` 通过 `/proc/cpuinfo` 探测 AVX-512，无则自动打补丁，
  有则保持上游最优路径——同一个脚本在 Xeon 上依然走上游 `v4` 编译。

**代价（必须说明）**：AVX2 基线下，少量依赖 AVX-512/AMX 的量化 GEMM
（fp8 / int4 / int8）与 VNNI 优化路径不可用，会走通用实现，绝对吞吐低于 Xeon。
但 bf16/fp32 的正常推理路径完整可用（本次使用 Qwen3-0.6B bf16，不受影响）。

服务端日志可确认这条回退路径确实生效：

```
The current platform does not support Intel AMX, will fallback to torch_native backend.
server_args=ServerArgs(..., attention_backend='torch_native', ...)
```

---

## 4. 其他值得记录的坑

| 问题 | 根因 | 修法 |
|---|---|---|
| `github.com` 在 WSL 内解析为 `127.0.0.1`，`git clone` 直接失败 | Watt Toolkit (Steam++) 的 GitHub 加速在 **Windows hosts 文件**中写入了 27 条 `127.0.0.1` 条目，WSL 通过 DNS 代理继承 | 把大文件**提前在 Windows 侧预取**、让 WSL 侧完全离线构建（本仓库采用的方案）；推送时则在 WSL 内写入真实 IP 绕过劫持 |
| 脚本莫名以 `unbound variable` 退出 | `MODEL_ID="${VAR:-default}"# 中文注释` —— `#` 前少一个空格，bash 把整行解析为"赋值 + 要执行的命令"，变量只作用于那条命令的子环境，**并未真正赋值** | 补一个空格。教训：`#` 前永远留空格 |
| 装 Ray 时报"依赖无解" | 为把 torch 指向 CPU 索引而设的 `UV_CONFIG_FILE` 被全局导出，导致 Ray 的依赖解析也被限制在 PyTorch 索引内 | 装 Ray 前 `unset UV_CONFIG_FILE` |
| 终端截图总被裁掉一半 | CSS 中 `white-space: pre` 加在了容器上，HTML 源码里 `<div>` 之间的换行符也被渲染成换行，实际行高翻倍 | `pre` 只加在每行元素上；并改为"渲染后按内容自动裁剪"，彻底摆脱对字体度量的估算 |
| Ubuntu 26.04 自带 Python 3.14，装不上 torch | SGLang / Ray 官方 CPU 配方基于 3.12 | 解压 standalone CPython 3.12 + `uv venv`，不动系统 Python |

---

## 5. 复现步骤

### 5.1 预取大文件（在能访问 GitHub / HuggingFace 的一侧执行）

```bash
python tools/fetch_all.py        # 下载 trace、SGLang 源码包、CPython、Qwen3-0.6B 权重
```

> 这一步是为了让 WSL 侧**完全不依赖外网**，从而避开 Watt Toolkit 的 MITM 干扰。

### 5.2 一键执行（在 WSL 内）

```bash
sudo bash wsl/run_all.sh
```

或分步执行：

```bash
sudo bash wsl/01_setup_env.sh        # 建环境 + 编译 sgl-kernel（最耗时）
sudo bash wsl/02_start_server.sh     # 起 Ray head + SGLang 服务
sudo bash wsl/03_single_request.sh   # 截图1 的原始证据
sudo bash wsl/06_make_shots.sh       # 汇编截图文本
# 压测（用 SGLang 环境的 python）
source /mnt/d/first-task/work/env.sh
$VENV/bin/python wsl/04_benchmark.py --n 20 --mean-interval 2.0 --input-cap 1024 --out-cap 64
```

`01_setup_env.sh` 会自动：探测 AVX-512 → 需要时打 ISA 补丁 →
本地解压 CPython/源码/模型 → 建两个隔离 venv（SGLang 与 Ray）→ 编译 → 写 `env.sh`。
脚本**幂等**，可重复执行；`sgl-kernel` 编译有守卫，已装则跳过。

### 5.3 生成 PDF 交付物

`report/src/*.html` 是全部 PDF 的**可复现源文件**，用本机 Chrome 无头模式渲染：

```bash
python -m pip install pymupdf                    # 仅用于反渲染质检
# HTML → PDF（A4）
chrome --headless=new --no-pdf-header-footer \
       --print-to-pdf=out.pdf file:///<绝对路径>/report/src/重点回答.html
```

---

## 6. 压测设计

| 项 | 设置 | 说明 |
|---|---|---|
| 数据源 | `arxiv-trace/mooncake_trace.jsonl` | 共 **23608** 条记录 |
| 采样 | 随机 **20** 条，`seed=2026` | 满足题目 10~30 条要求 |
| Prompt 构造 | 按记录的 `input_length` / `output_length` | 用确定性伪学术语料拼装，token 数用真实 tokenizer 校验 |
| 到达过程 | **Poisson**，λ = 0.5 req/s（平均间隔 2.0 s） | 间隔 ~ Exp(1/λ)，总到达跨度 58.8 s |
| 公共前缀 | **256** tokens | 见下 |
| 长度上限 | input ≤ 1024，output ≤ 64 | **CPU 上的必要工程取舍**，见下 |

### 为什么设长度上限

trace 的输入长度中位数为 **6345**、p95 达 **26081**、最大 **125546** tokens。
在纯 CPU 上这不现实：42K token 的 KV cache 约需 4.7 GB，且实测 2048 token 上下文的
prefill 单次就要 5~15 s、解码仅约 0.5~2 tok/s（短提示时可达 21 tok/s）。
因此把长度截断到 CPU 可承载的范围，并在交付文档中如实标注。
**这是工程取舍，不是对指标的粉饰。**

### 为什么让所有请求共享前缀

先统计了 trace 的字段：**23608 条记录中 `hash_ids[0]` 只有 4 个不同取值，
最常见者占 46.3%** —— 说明真实负载天然存在共享前缀。因此令所有压测请求
共享 256 token 前缀，以真实触发 RadixCache 的前缀复用（而非只在理论上讨论）。

---

## 7. 实测结果

```
采样来源 : Mooncake FAST'25  arxiv-trace/mooncake_trace.jsonl (共 23608 条, 随机采样 20 条, seed=2026)
到达过程 : Poisson, λ=0.5000 req/s (平均间隔 2.00s)
公共前缀 : 256 tokens
成功率   : 20/20 = 100.0%     总墙钟 72.8s     输出吞吐 12.28 tok/s
TTFT(ms) : avg=2113.5  p50=1414.1  p90=3952.1  min=639.3  max=5883.7
Latency  : avg=25574.7ms  p50=23812.2ms  p90=44506.9ms
```

### 服务端前缀复用证据

`evidence/sglang_server.log` 中的 `Prefill batch` 行可直接观测 RadixCache 命中
（`#cached-token > 0` 即该请求的部分前缀被复用、对应 prefill 被跳过）：

```
[2026-09-26 10:51:15] Prefill batch, #new-seq: 1, #new-token: 661,  #cached-token: 256,  #running-req: 3, ...
[2026-09-26 10:51:18] Prefill batch, #new-seq: 1, #new-token: 745,  #cached-token: 279,  #running-req: 4, ...
[2026-09-26 10:51:24] Prefill batch, #new-seq: 2, #new-token: 769,  #cached-token: 1279, #running-req: 6, ...
```

全程 **38 个 prefill 批次中 29 个命中，占比 76.3%**；命中长度以 256
（即共享前缀长度）与 1023/1024（整段 prompt 已被缓存）为主。
同时可见：大批次（`#new-token ≥ 600`，共 12 个）时服务端自报 prefill 输入吞吐
**214~423 tok/s**；小批次的瞬时值受日志 1 秒时间粒度限制，不具参考意义。

### 服务端关键配置（启动日志）

```
KV Cache is allocated. dtype: torch.bfloat16, #tokens: 81261, K size: 4.34 GB, V size: 4.34 GB
max_total_num_tokens=81261, chunked_prefill_size=2048, max_prefill_tokens=16384,
max_running_requests=2048, context_len=40960
Tree cache initialized: source=default impl=RadixCache ...
```

---

## 8. 目录结构

```
.
├── deliverables/          6 份 PDF 交付物
├── wsl/                   WSL 端全套可复现脚本
│   ├── 00_common.sh           公共配置、apt/LD_PRELOAD/下载、PATH、CPU 指令集探测
│   ├── 01_setup_env.sh        环境 + 编译（自动决定是否打 ISA 补丁）
│   ├── 02_start_server.sh     启动 Ray head + SGLang 服务
│   ├── 03_single_request.sh   /v1/models + 单次推理（截图1 证据）
│   ├── 04_benchmark.py        Mooncake 采样 + Poisson 压测
│   ├── 05_patch_cpu_isa.sh    ★ AVX2 基线补丁（本仓库最关键的一处修复）
│   ├── 06_make_shots.sh       从真实日志汇编截图文本
│   ├── 99_selfcheck.sh        环境自检
│   └── run_all.sh             全流程串联
├── tools/                 跨平台工具
│   ├── fetch_all.py           预取大文件（让 WSL 侧离线可构建）
│   ├── make_shot.py           终端文本 → 截图 PNG（自适应高度 + 自动裁剪）
│   └── make_ops_pdf.py        截图 → A4 PDF（早期 PyMuPDF 拼接方案；正式交付件由 report/src/操作保存.html 渲染）
├── report/src/            全部 PDF 的 HTML 源文件（可复现）
└── evidence/              原始证据：日志、指标、截图、逐请求结果
```

---

## 9. 说明

- 所有日志、指标与截图**均取自真实运行过程**，未做人工改写或美化。
- `evidence/shot1.txt`（截图1 的文本来源）与 `evidence/shot1_raw.txt`（`03_single_request.sh` 的原始落盘）
  **并非同一次调用**：前者由 `06_make_shots.sh` 在汇编时另发起一次真实 HTTP 请求并摘要关键字段生成，
  因此二者的 `id` 与 `usage` 不同（`completion_tokens` 256 vs 250，源于采样随机性以及是否触达
  `max_tokens` 上限——256 那次 `finish_reason=length`，250 那次 `stop`）。两处都是真实响应，无人工编造。
- `wsl/` 下所有脚本为 **LF 换行**（`.gitattributes` 已固化），避免 `bad interpreter: ^M`。
- 压测的实测原始数据见 `evidence/benchmark_results.csv` / `.json`。
