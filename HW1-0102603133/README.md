# 第一次挑战：部署 SGLang 并回放 Mooncake 小 workload

## 环境

| 项目 | 要求 / 本仓库核验环境 |
| --- | --- |
| OS | Ubuntu / WSL |
| SGLang | 0.5.14 |
| Ray | 2.56.0 |
| 模型 | Qwen/Qwen3-0.6B |
| 本机核验 | 无 NVIDIA GPU。使用 `src/mock_sglang_server.py` 提供与 SGLang 相同的 HTTP 契约（`/v1/models`、`/v1/chat/completions`、`/generate`、`/flush_cache`，RadixCache 按 token 最长前缀匹配）。 |

GPU 机器上把 BASE URL 换成真实 `sglang.launch_server` 即可用同一套客户端脚本。

## 安装（GPU 真机）

```bash
# Python 3.10+
pip install "sglang[all]==0.5.14" "ray==2.56.0"
```

SGLang 与 Ray 可以放在不同虚拟环境，通过 HTTP 通信。

## 启动服务

```bash
# 真实 SGLang
python -m sglang.launch_server \
  --model-path Qwen/Qwen3-0.6B \
  --host 0.0.0.0 \
  --port 30000

# 本仓库 CPU 核验
python3 src/mock_sglang_server.py
```

等到日志出现 `The server is fired up and ready to roll!`。

## 回放命令

```bash
python3 src/make_mooncake_sample.py
python3 src/sample_mooncake_workload.py \
  --trace data/mooncake_trace.sample.jsonl \
  --out data/mooncake_sample.json \
  --n 20 --seed 2026 --rate 4.0

python3 src/run_single_request.py \
  --base http://127.0.0.1:30000 \
  --model Qwen/Qwen3-0.6B \
  --out results/single_request.json

python3 src/run_mooncake_workload.py \
  --base http://127.0.0.1:30000 \
  --workload data/mooncake_sample.json \
  --out results/mooncake_replay.json

python3 src/render_assets.py
```

完整 trace 可从 https://github.com/kvcache-ai/Mooncake/tree/main/FAST25-release/arxiv-trace 获取 `mooncake_trace.jsonl`，把 `--trace` 指向该文件。

## 脚本用途

| 路径 | 作用 |
| --- | --- |
| `src/mock_sglang_server.py` | 协议兼容服务，供无 GPU 核验 |
| `src/make_mooncake_sample.py` | 写入 20 条短记录 JSONL |
| `src/sample_mooncake_workload.py` | 采样并生成泊松到达 synthetic prompt |
| `src/run_single_request.py` | 截图1：`/v1/models` + 一次 chat 推理 |
| `src/run_mooncake_workload.py` | 截图2：回放 workload，记录 tokens/status/TTFT |
| `src/render_assets.py` | 生成全部交付 PDF |

## 交付文件

- `操作保存.pdf` 截图1+截图2
- `流程图.pdf`
- `重点回答.pdf`
- `作业感受.pdf`
- `AI使用说明情况.pdf`
- `阅读文献笔记.pdf`

## GitHub

将本目录推到公开仓库后提交仓库链接。
