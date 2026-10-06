# HW2：第二次挑战（前缀缓存测量 + SGLang 请求流程阅读）

- GPU：4 × NVIDIA GeForce RTX 4090 D（24 GB）单机（AutoDL/SeetaCloud），驱动 580.105.08，CUDA 13.0
- 软件：SGLang 0.5.14（torch 2.11.0+cu130、transformers 5.8.1，Python 3.12），Ray 2.56.0（本关未用到集群）
- 模型：Qwen/Qwen3-0.6B，本地路径 `/root/autodl-tmp/models/Qwen3-0.6B`（hf-mirror 下载）
- RadixCache 保持默认开启

## 安装方法

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
python -m venv /root/autodl-tmp/envs/sgl
/root/autodl-tmp/envs/sgl/bin/pip install ninja
/root/autodl-tmp/envs/sgl/bin/pip install "sglang[all]==0.5.14" "torch==2.11.0" "transformers==5.8.1"
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download Qwen/Qwen3-0.6B \
  --local-dir /root/autodl-tmp/models/Qwen3-0.6B
```

## 启动与回放命令

```bash
/root/autodl-tmp/envs/sgl/bin/python -m sglang.launch_server \
  --model /root/autodl-tmp/models/Qwen3-0.6B --host 0.0.0.0 --port 30000

# 目标一测量（共享前缀 / 分散前缀两组自动各跑一轮）
/root/autodl-tmp/envs/sgl/bin/python src/target1/measure_prefix_cache.py \
  --base-url http://127.0.0.1:30000 --output-dir results/target1
```

脚本行为：两组各 32 条测量请求、最大并发 8，统一 temperature=0、max_new_tokens=16、
ignore_eos=true、sampling_seed=2026，序列等长（1152 = 1024 前缀 + 128 后缀）；服务级预热
→ 每组先等在飞结束并 POST /flush_cache 确认成功 → 共享前缀组再发 1 条预热请求载入公共前缀
（不计入结果）→ 并发回放，从流式响应的 meta_info 解析 cached_tokens / prompt_tokens /
completion_tokens / ttft / tpot。

## 脚本用途

| 脚本 | 作用 |
| --- | --- |
| `src/target1/measure_prefix_cache.py` | 目标一全部逻辑：构造两组负载、预热、flush、并发回放、逐请求 CSV 与汇总 JSON |

## 结果目录与报告表格的对应关系

```text
results/target1/
├── shared_prefix/       -> 报告 §2 主表「共享前缀组」列（requests.csv 逐请求, summary.json 汇总）
├── dispersed_prefix/    -> 报告 §2 主表「分散前缀组」列（requests.csv 逐请求, summary.json 汇总）
└── compare.json         -> 两组对照（命中率、prefill、TTFT/TPOT/端到端 p50/p95）
```

报告任务二的流程图与说明中的文件：行号，均在本机安装的 SGLang 0.5.14 源码
（`site-packages/sglang/srt/...`）中用 grep 定位核对，可在同版本源码中逐一检索验证。
