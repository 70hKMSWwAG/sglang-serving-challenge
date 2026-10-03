# HW2 - SGLang 前缀缓存测量与请求流程分析

## 环境与软件版本
- OS: Ubuntu 24.04（2 vCPU / 7.4GB RAM，无 GPU，使用 CPU 推理）
- Python 3.11.16
- SGLang 0.5.14
- Ray 2.56.0
- 模型: Qwen/Qwen3-0.6B
- vLLM 0.11.0（仅用于提供 `vllm._custom_ops` CPU 算子，--no-deps 安装）

## 安装方法
```bash
uv venv ~/sglenv --python 3.11
source ~/sglenv/bin/activate
uv pip install "sglang==0.5.14" "ray==2.56.0" huggingface_hub
uv pip install "vllm==0.11.0" --no-deps   # CPU rotary/ops 支持
```

## 启动服务
```bash
python -m sglang.launch_server \
  --model-path Qwen/Qwen3-0.6B \
  --device cpu --attention-backend torch_native \
  --mem-fraction-static 0.8 --watchdog-timeout 100000 \
  --max-running-requests 8 \
  --host 127.0.0.1 --port 30000
```

## 测量脚本（src/measure_prefix_cache.py）
- 构造两组各 32 条请求：`dispersed_prefix`（每条请求前缀互不相同）与 `shared_prefix`（共享 256-token 前缀）；
- 输入 512 tokens = 256 前缀 + 256 独有后缀，输出 16 tokens；
- sampling_seed=2026, temperature=0, ignore_eos=true, 流式 `/generate` + input_ids；
- 每组前先短请求预热 + POST /flush_cache，shared 组先发一条预热请求（不计入结果）；
- 最大并发 8（ThreadPoolExecutor，同时受服务端 --max-running-requests 8 约束）。

```bash
python src/measure_prefix_cache.py results/target1/myrun/prefix_cache.jsonl
```

## 回放命令
```bash
# 服务就绪后
python src/measure_prefix_cache.py ~/hw2/results/target1/myrun/prefix_cache.jsonl
python src/gen_pdfs.py hw2       # 重新生成 HW2 报告 PDF（含合并版 report.pdf）
```

## 结果目录与报告表格对应关系
- `results/target1/dispersed_prefix/per_request.jsonl` — 分散前缀组逐请求记录
- `results/target1/dispersed_prefix/summary.json` — 分散前缀组汇总
- `results/target1/shared_prefix/per_request.jsonl` — 共享前缀组逐请求记录
- `results/target1/shared_prefix/summary.json` — 共享前缀组汇总
- `results/target1/comparison_table.json` — 两组对照表（report.pdf 任务一表格的数据来源：TTFT/TPOT/E2E p50、p95、命中率、实际 Prefill tokens）
- `results/target1/task2_source_flow.md` — 任务二源码流程追踪文字稿
- `task1_results.pdf` / `task2_flow.pdf` — 任务一/任务二分册
- `作业感受.pdf` — 第二次挑战作业感受（三问）
- `report.pdf` — 合订版报告（任务一 + 任务二 + AI 使用说明 + 作业感受）
- `AI 使用说明情况（第二次挑战）.pdf` — 按作业要求命名
