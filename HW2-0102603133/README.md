# HW2 测量 SGLang 前缀缓存并阅读请求主流程

## GPU 与软件版本

| 项目 | 值 |
| --- | --- |
| 要求 | SGLang 0.5.14，Ray 2.56.0，Qwen/Qwen3-0.6B，Radix Cache 开启 |
| 本仓库核验主机 | x86_64 CPU，无 NVIDIA GPU / CUDA |
| 核验后端 | `src/target1/server.py`（与 SGLang `/generate` 流式、`cached_tokens`、`/flush_cache` 契约一致） |

## 安装

```bash
# GPU 真机
pip install "sglang[all]==0.5.14" "ray==2.56.0"
```

核验环境只需 Python 3.10+ 标准库（测量脚本）以及生成 PDF 时的 `reportlab`、`pillow`。

## 启动

```bash
# 真实 SGLang，保持 Radix Cache 开启（默认不要加 --disable-radix-cache）
python -m sglang.launch_server \
  --model-path Qwen/Qwen3-0.6B \
  --host 0.0.0.0 \
  --port 30000

# CPU 核验
python3 src/target1/server.py
```

## 回放任务一

```bash
python3 src/target1/measure_prefix_cache.py \
  --base http://127.0.0.1:30000 \
  --results-root results/target1

python3 src/render_report.py
```

测量脚本会：短请求预热服务 -> 每组 `POST /flush_cache` -> 共享组再发一条前缀预热（不计入）-> 32 条流式 `/generate`（`input_ids`，并发 8）。

## 脚本用途

| 路径 | 作用 |
| --- | --- |
| `src/target1/server.py` | 协议兼容 SGLang 服务 |
| `src/target1/mock_sglang_server.py` | 转发到同一实现 |
| `src/target1/measure_prefix_cache.py` | 任务一对照实验 |
| `src/render_report.py` | 由 results JSON 生成 report.pdf 与 AI 说明 PDF |

## 结果目录与报告表格对应关系

| 报告内容 | 文件 |
| --- | --- |
| 共享前缀逐请求 | `results/target1/shared_prefix/per_request.jsonl` |
| 共享前缀汇总 | `results/target1/shared_prefix/summary.json` |
| 分散前缀逐请求 | `results/target1/dispersed_prefix/per_request.jsonl` |
| 分散前缀汇总 | `results/target1/dispersed_prefix/summary.json` |
| 对照表与完成标准 | `results/target1/comparison.json` |
| flush 响应 | `*/flush_cache.json` |
| 共享前缀预热（不计分） | `shared_prefix/prefix_warmup.json` |

报告主表列：成功率、吞吐、缓存命中率、实际 Prefill token、TTFT/TPOT/E2E 的 p50 与 p95。公式：

```
缓存命中率 = sum(cached_tokens) / sum(prompt_tokens)
实际 Prefill token 数 = sum(prompt_tokens - cached_tokens)
```

## 任务二源码锚点（v0.5.14）

- `TokenizerManager.generate_request` — `python/sglang/srt/managers/tokenizer_manager.py:576`
- `Scheduler.event_loop_normal` — `python/sglang/srt/managers/scheduler.py:1505`
- `Scheduler.get_new_batch_prefill` — `scheduler.py:2702`
- `match_prefix_for_req` — `python/sglang/srt/managers/schedule_policy.py:85`
- `RadixCache.match_prefix` — `python/sglang/srt/mem_cache/radix_cache.py:358`
- `PrefillAdder` — `schedule_policy.py:425`
- `RadixCache.cache_finished_req` / `cache_unfinished_req` — `radix_cache.py:438` / `:485`
- 流式输出 — `tokenizer_manager.py` `handle_loop:1824`，`_wait_one_response:1425`
