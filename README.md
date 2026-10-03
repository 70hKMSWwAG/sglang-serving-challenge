# SGLang 挑战作业

本仓库包含两次挑战的可复现材料。当前核验环境无 NVIDIA GPU，使用协议兼容服务跑通脚本；GPU 机器把 BASE URL 换成真实 `sglang.launch_server` 即可。

## HW1

目录：`HW1-0102603133/`

交付 PDF：`操作保存.pdf`、`流程图.pdf`、`重点回答.pdf`、`作业感受.pdf`、`AI使用说明情况.pdf`、`阅读文献笔记.pdf`。

```bash
python3 HW1-0102603133/src/mock_sglang_server.py
python3 HW1-0102603133/src/make_mooncake_sample.py
python3 HW1-0102603133/src/sample_mooncake_workload.py \
  --trace HW1-0102603133/data/mooncake_trace.sample.jsonl \
  --out HW1-0102603133/data/mooncake_sample.json \
  --n 20 --seed 2026 --rate 4.0
python3 HW1-0102603133/src/run_single_request.py \
  --base http://127.0.0.1:30000 \
  --out HW1-0102603133/results/single_request.json
python3 HW1-0102603133/src/run_mooncake_workload.py \
  --base http://127.0.0.1:30000 \
  --workload HW1-0102603133/data/mooncake_sample.json \
  --out HW1-0102603133/results/mooncake_replay.json
python3 HW1-0102603133/src/render_assets.py
```

## HW2

目录：`HW2-0102603133/`，压缩包：`HW2-0102603133.zip`（解压后仅含同名根目录）。

```bash
python3 HW2-0102603133/src/target1/server.py
bash HW2-0102603133/scripts/run_target1.sh
```

任务一对照：`HW2-0102603133/results/target1/comparison.json`  
共享组命中率 0.9697、Prefill 2048；分散组命中率 0、Prefill 67584；32/32 成功。
