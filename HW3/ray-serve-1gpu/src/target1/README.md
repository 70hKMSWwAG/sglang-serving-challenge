# target1（前缀缓存测量）

本目录对应作业交付结构中的 `src/target1/`。

## 脚本

`measure_prefix_cache.py` 按挑战二"任务一"的规范实现前缀缓存两组对照测量：

- Radix Cache 开启，原生 `/generate` 接口发送 `input_ids`，流式接收；
- 每组 32 条测量请求、最大并发 8；
- 统一 `temperature=0、max_new_tokens=16、ignore_eos=true、sampling_seed=2026`；
- **shared_prefix 组**：输入 = 2048 token 共享前缀 + 64 token 独立后缀（共 2112）；
  测量前先发送 1 条包含共享前缀的预热请求（不计入结果）；
- **dispersed_prefix 组**：每条 2112 token，且全部 token 跨请求互不相同
  （用随机词表置换切片保证），不做前缀预热；
- 首次实验前用短请求完成服务预热；每组测量前等待请求排空、
  `POST /flush_cache` 并确认成功；
- 逐请求记录 input/prompt tokens、cached_tokens、output tokens、status、
  TTFT/TPOT/E2E；汇总写 `summary.json`（含命中率与实际 Prefill token 数）。

token id 由 `seed=2026` 的随机过程生成，可复现。

## 运行

```bash
# 需要一个已启动的 SGLang（如 launch_sglang.sh 的后端 0）
sglang-env/bin/python src/target1/measure_prefix_cache.py \
    --base-url http://127.0.0.1:30000 \
    --output-dir results/target1
```

结果写入 `results/target1/{shared_prefix,dispersed_prefix}/run-1/`
（`summary.json`、`requests.csv`，shared 组另有 `warmup.csv`）。

## 本次结果（2026-10-05，run-1）

| 负载 | 成功 | 吞吐 (req/s) | 命中率 | 实际 Prefill token | TTFT p50/p95 (ms) |
| --- | --- | --- | --- | --- | --- |
| shared_prefix | 32/32 | 16.74 | 97.06% | 1,985 | 95.8 / 106.7 |
| dispersed_prefix | 32/32 | 11.73 | 0.00% | 67,584 | 205.8 / 304.8 |

（理论命中上限 = 2048/2112 = 97.0%；预热请求使首条请求的后缀同样命中。）
