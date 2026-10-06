#!/usr/bin/env python3
"""
HW1 挑战内容 2：Mooncake FAST'25 trace 采样 workload 回放

步骤：
  1. 从 arxiv-trace/mooncake_trace.jsonl 采样 24 条请求记录
     （为适配无 GPU 的 CPU 推理环境，在 input_length<=2048、output_length<=128 的真实记录中采样，
       保持 trace 的长度分布特征，不做数值缩放；采样窗口与理由记录在 README/报告中）
  2. 按 input_length 构造 synthetic prompt（真实英文语料拼接后精确截断到目标长度）
  3. 用 Poisson 到达过程生成请求到达时间（指数分布间隔）
  4. 按到达时间把请求发送到本地 SGLang OpenAI 兼容服务（/v1/chat/completions，流式）
  5. 逐请求记录 input tokens / output tokens / status / TTFT / latency，并输出 CSV 与控制台表格

用法：
  python3 mooncake_workload.py --num-requests 24 --mean-interval 3.0
"""

import argparse
import asyncio
import csv
import json
import os
import random
import statistics
import time
from pathlib import Path

import aiohttp
from transformers import AutoTokenizer

MODEL_PATH = os.environ.get("MODEL_PATH", "/workspace/models/Qwen3-0.6B")
# trace 查找顺序：环境变量 MOONCAKE_TRACE → 仓库内 data/ → 沙箱绝对路径
_TRACE_CANDIDATES = [
    os.environ.get("MOONCAKE_TRACE"),
    Path(__file__).resolve().parent.parent / "data" / "mooncake_trace.jsonl",
    Path("/workspace/data/mooncake_trace.jsonl"),
]
TRACE_PATH = next((str(p) for p in _TRACE_CANDIDATES if p and Path(p).exists()),
                  str(_TRACE_CANDIDATES[1]))
DEFAULT_URL = "http://127.0.0.1:30000"

CORPUS = (
    "A serving system for large language models receives heterogeneous requests whose prompts "
    "range from short instructions to long documents. The scheduler must decide which requests "
    "to admit, how to batch them, and how much key value cache to reserve for the decode phase. "
    "Prefix reuse lets a new request skip the prefill computation of tokens whose keys and values "
    "are already resident in the cache. Under Poisson arrivals the queue length fluctuates, so the "
    "observed time to first token reflects both service time and waiting time. Measuring both "
    "quantiles and averages is necessary because tail latency dominates the user experience. "
)


def load_trace_samples(num_requests, seed, max_input=2048, max_output=128):
    """从 Mooncake trace 采样记录（限定长度窗口以适配 CPU 推理预算）。"""
    rows = []
    with open(TRACE_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r["input_length"] <= max_input and r["output_length"] <= max_output:
                rows.append(r)
    assert rows, "no candidate rows in trace"

    rng = random.Random(seed)
    rng.shuffle(rows)
    samples = rows[:num_requests]
    # 保持 trace 中的原始时间顺序特征：按 timestamp 排序
    samples.sort(key=lambda r: r["timestamp"])
    return samples, len(rows)


def build_prompt_ids(tokenizer, target_len, seed):
    """构造长度精确等于 target_len 的 synthetic prompt（语料循环拼接后截断）。"""
    rng = random.Random(seed)
    sentences = CORPUS.split(". ")
    rng.shuffle(sentences)
    text = ". ".join(sentences) + "."
    ids = tokenizer.encode(text)
    while len(ids) < target_len:
        rng.shuffle(sentences)
        ids.extend(tokenizer.encode(". ".join(sentences) + "."))
    return ids[:target_len]


async def run(args):
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
    samples, n_candidates = load_trace_samples(args.num_requests, args.seed)
    print(f"[trace] 候选记录 {n_candidates} 条，采样 {len(samples)} 条 "
          f"(input<=2048, output<=128)")

    # 泊松到达：指数分布间隔
    rng = random.Random(args.seed + 1)
    intervals = [rng.expovariate(1.0 / args.mean_interval) for _ in range(len(samples))]
    arrival = []
    acc = 0.0
    for x in intervals:
        acc += x
        arrival.append(acc)

    # 构造每条请求的 prompt 文本：token 化后精确截断到 trace 的 input_length
    prompts = []
    for i, s in enumerate(samples):
        ids = build_prompt_ids(tokenizer, s["input_length"], seed=1000 + i)
        text = tokenizer.decode(ids)
        prompts.append(text)

    # 取服务端注册的 model id
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{args.url}/v1/models", timeout=60) as resp:
            models = await resp.json()
    model_id = models["data"][0]["id"]

    results = []
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=600)
    t_start = time.perf_counter()

    async def one(i, s):
        # 等到泊松到达时刻再发送
        wait = arrival[i] - (time.perf_counter() - t_start)
        if wait > 0:
            await asyncio.sleep(wait)
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompts[i]}],
            "max_tokens": s["output_length"],
            "temperature": 0,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        t0 = time.perf_counter()
        ttft = None
        t_last = None
        usage = {}
        status = None
        error = None
        async with session.post(f"{args.url}/v1/chat/completions", json=payload, timeout=timeout) as resp:
            status = resp.status
            if status != 200:
                error = (await resp.text())[:200]
            else:
                async for raw in resp.content:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    now = time.perf_counter()
                    if obj.get("usage"):
                        usage = obj["usage"]
                    choices = obj.get("choices") or []
                    if choices and ttft is None:
                        delta = choices[0].get("delta") or {}
                        if delta.get("content"):
                            ttft = now - t0
                    t_last = now
        latency = (t_last - t0) if t_last else None
        r = {
            "index": i,
            "trace_input_length": s["input_length"],
            "trace_output_length": s["output_length"],
            "scheduled_arrival_s": round(arrival[i], 3),
            "actual_send_s": round(time.perf_counter() - t_start, 3),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "status": status,
            "ttft_s": round(ttft, 3) if ttft else None,
            "latency_s": round(latency, 3) if latency else None,
            "error": error,
        }
        print(f"[{i:02d}] send={r['actual_send_s']:7.2f}s status={r['status']} "
              f"in={r['input_tokens']} out={r['output_tokens']} "
              f"ttft={r['ttft_s']} latency={r['latency_s']}")
        return r

    async with aiohttp.ClientSession(timeout=timeout) as session:
        results = await asyncio.gather(*[one(i, s) for i, s in enumerate(samples)])

    wall = time.perf_counter() - t_start

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = outdir / "workload_results.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        for r in results:
            w.writerow(r)

    ok = [r for r in results if r["status"] == 200]
    ttfts = [r["ttft_s"] for r in ok if r["ttft_s"]]
    lats = [r["latency_s"] for r in ok if r["latency_s"]]

    def pct(v, q):
        v = sorted(v)
        if not v:
            return None
        k = (len(v) - 1) * q / 100.0
        lo, hi = int(k), min(int(k) + 1, len(v) - 1)
        return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 3)

    summary = {
        "num_requests": len(results),
        "num_success": len(ok),
        "success_rate": round(len(ok) / len(results), 4),
        "wall_clock_s": round(wall, 3),
        "mean_interval_s": args.mean_interval,
        "total_input_tokens": sum(r["input_tokens"] or 0 for r in ok),
        "total_output_tokens": sum(r["output_tokens"] or 0 for r in ok),
        "output_token_throughput_tps": round(sum(r["output_tokens"] or 0 for r in ok) / wall, 3),
        "ttft_mean_s": round(statistics.mean(ttfts), 3) if ttfts else None,
        "ttft_p50_s": pct(ttfts, 50),
        "ttft_p95_s": pct(ttfts, 95),
        "latency_mean_s": round(statistics.mean(lats), 3) if lats else None,
        "latency_p50_s": pct(lats, 50),
        "latency_p95_s": pct(lats, 95),
    }
    with open(outdir / "workload_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n===== WORKLOAD SUMMARY =====")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nCSV: {csv_path}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--num-requests", type=int, default=24)
    ap.add_argument("--mean-interval", type=float, default=3.0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", default="/workspace/HW1/results")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
