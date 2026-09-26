#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
04_benchmark.py —— Mooncake FAST'25 trace 采样 + Poisson 到达过程 workload

任务要求对应：
  从 Mooncake FAST'25 trace (arxiv-trace/mooncake_trace.jsonl) 采样 10~30 条请求，
  按 input_length / output_length 构造 synthetic prompt，
  用 Poisson 到达过程生成请求时间，发送到 SGLang，
  记录每个请求的 input tokens / output tokens / status / TTFT / latency。

设计要点：
  * trace 中所有记录共享 hash_ids[0]（公共前缀），因此这里同样让每个 prompt
    共享一段定长前缀，可真实触发 SGLang 的 RadixCache 前缀复用。
  * 用 http.client 直连 127.0.0.1，完全绕开系统代理（Watt Toolkit 等）对本地回环的拦截。
  * 到达过程严格为泊松过程：相邻到达间隔 ~ Exp(1/mean_interval)。
"""

import argparse
import csv
import http.client
import json
import math
import os
import random
import statistics
import sys
import threading
import time

# ----------------------------------------------------------------------------- 参数
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "30000")))
    p.add_argument("--model", default=os.environ.get("MODEL_ID", "Qwen/Qwen3-0.6B"))
    p.add_argument("--model-dir", default=os.environ.get("MODEL_DIR", ""))
    p.add_argument("--trace", default=os.environ.get("TRACE_FILE", ""))
    p.add_argument("--out-dir", default=os.environ.get("RESD", "./results"))
    p.add_argument("--n", type=int, default=20, help="采样请求条数（10~30）")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--mean-interval", type=float, default=6.0,
                   help="泊松到达的平均间隔(秒)，λ = 1/mean_interval")
    p.add_argument("--prefix-tokens", type=int, default=512,
                   help="所有请求共享的公共前缀 token 数（对应 trace 的 hash_ids[0]）")
    p.add_argument("--input-cap", type=int, default=0, help="0=不截断，否则限制 input 长度上限")
    p.add_argument("--out-cap", type=int, default=0, help="0=不截断，否则限制 output 长度上限")
    p.add_argument("--timeout", type=float, default=1200.0, help="单请求超时(秒)")
    p.add_argument("--warmup", type=int, default=1, help="正式压测前的预热请求数")
    p.add_argument("--num-parallel", type=int, default=0, help="预留；本脚本用纯泊松到达")
    return p.parse_args()

ARGS = parse_args()
os.makedirs(ARGS.out_dir, exist_ok=True)

def log(*a):
    print(*a, flush=True)

# ----------------------------------------------------------------------------- trace
TRACE_URLS = [
    "https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/arxiv-trace/mooncake_trace.jsonl",
    "https://gh-proxy.com/https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/arxiv-trace/mooncake_trace.jsonl",
    "https://cdn.jsdelivr.net/gh/kvcache-ai/Mooncake@main/FAST25-release/arxiv-trace/mooncake_trace.jsonl",
]

def ensure_trace(path: str) -> str:
    if path and os.path.isfile(path) and os.path.getsize(path) > 1000:
        return path
    cand = path or os.path.join(ARGS.out_dir, "..", "data", "mooncake_trace.jsonl")
    cand = os.path.abspath(cand)
    os.makedirs(os.path.dirname(cand), exist_ok=True)
    if os.path.isfile(cand) and os.path.getsize(cand) > 1000:
        return cand
    import subprocess
    for u in TRACE_URLS:
        log(f"  下载 trace: {u}")
        r = subprocess.run(["curl", "-fsSL", "--connect-timeout", "25", "--max-time", "600",
                            "-o", cand, u], capture_output=True)
        if r.returncode == 0 and os.path.getsize(cand) > 1000:
            return cand
    raise SystemExit("Mooncake trace 下载失败")

def load_trace(path):
    recs = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if "input_length" in o and "output_length" in o:
                recs.append(o)
    return recs

# ----------------------------------------------------------------------------- synthetic prompt
SENTENCES = [
    "We present a distributed cache architecture that decouples the prefetch and eviction paths.",
    "The key observation is that long-context inference is dominated by memory bandwidth, not FLOPs.",
    "Prefix sharing across requests allows the runtime to amortize prefill computation.",
    "Our evaluation uses a production trace containing thousands of anonymized conversations.",
    "Attention is computed with grouped-query attention to reduce the size of the key-value cache.",
    "Chunked prefill improves inter-token latency by interleaving prefill and decode batches.",
    "We tokenize the corpus with a byte-pair encoding vocabulary of one hundred fifty thousand entries.",
    "The scheduler admits requests subject to a global memory budget and a token budget per iteration.",
    "Radix structures permit longest-prefix matching over self-contained sequences of tokens.",
    "Continuous batching keeps the accelerator saturated when output lengths are heterogeneous.",
    "Speculative decoding can reduce the number of sequential forward passes at the cost of extra compute.",
    "Quantization to eight bits reduces the footprint of the weights but may affect quality.",
    "Tensor parallelism splits the weight matrices across devices and requires an all-reduce per layer.",
    "The results show a substantial reduction in time to first token for workloads with shared prefixes.",
    "Memory fragmentation is avoided by paging the key-value cache into fixed-size blocks.",
    "Throughput and latency trade off against each other as the batch size is increased.",
    "We measure end-to-end latency on a single socket server with a fixed arrival process.",
    "An ablation study isolates the contribution of the cache hit rate to the overall speedup.",
    "Requests are processed in arrival order within the same priority class in our implementation.",
    "The overhead of the radix tree is negligible relative to the cost of a single attention layer.",
]

def build_corpus(tokenizer, need_tokens: int, seed: int) -> str:
    """生成足够长（>= need_tokens）的确定性伪学术文本。"""
    rng = random.Random(seed)
    parts, total = [], 0
    while total < need_tokens + 2048:
        para = " ".join(rng.choice(SENTENCES) for _ in range(6))
        parts.append(para)
        total += len(para.split())
    return "\n\n".join(parts)

# ----------------------------------------------------------------------------- HTTP
def post_stream(path, payload, timeout):
    """以流式方式 POST，返回 (status, ttft_ms, latency_ms, text, usage, error)"""
    body = json.dumps(payload).encode("utf-8")
    conn = http.client.HTTPConnection(ARGS.host, ARGS.port, timeout=timeout)
    t0 = time.perf_counter()
    ttft = None
    chunks, usage, err = [], None, None
    status = None
    try:
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        resp = conn.getresponse()
        status = resp.status
        if status != 200:
            err = resp.read().decode("utf-8", "replace")[:400]
        else:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                for ch in obj.get("choices", []):
                    piece = None
                    if ch.get("text") is not None:
                        piece = ch["text"]
                    elif isinstance(ch.get("delta"), dict) and ch["delta"].get("content"):
                        piece = ch["delta"]["content"]
                    if piece:
                        if ttft is None:
                            ttft = (time.perf_counter() - t0) * 1000.0
                        chunks.append(piece)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        status = status or 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
    latency = (time.perf_counter() - t0) * 1000.0
    return status, ttft, latency, "".join(chunks), usage, err

# ----------------------------------------------------------------------------- main
def main():
    log("=" * 78)
    log("Mooncake FAST'25 trace 采样 + Poisson 到达 workload")
    log("=" * 78)

    trace_path = ensure_trace(ARGS.trace)
    recs = load_trace(trace_path)
    log(f"trace 文件     : {trace_path}")
    log(f"trace 记录总数 : {len(recs)}")

    rng = random.Random(ARGS.seed)
    sampled = rng.sample(recs, ARGS.n)
    log(f"采样条数       : {len(sampled)}  (seed={ARGS.seed})")

    # ---- tokenizer ----
    from transformers import AutoTokenizer
    tok_path = ARGS.model_dir or ARGS.model
    tokenizer = AutoTokenizer.from_pretrained(tok_path, trust_remote_code=True)

    max_in = max(r["input_length"] for r in sampled)
    if ARGS.input_cap:
        max_in = min(max_in, ARGS.input_cap)
    corpus = build_corpus(tokenizer, max_in + 2048, ARGS.seed)
    base_ids = tokenizer.encode(corpus)
    log(f"语料 token 数  : {len(base_ids)}  (需要 >= {max_in})")

    P = min(ARGS.prefix_tokens, max_in // 4)
    prefix_text = tokenizer.decode(base_ids[:P])

    # ---- 构造 synthetic prompt ----
    jobs = []
    for i, r in enumerate(sampled):
        L = int(r["input_length"])
        if ARGS.input_cap:
            L = min(L, ARGS.input_cap)
        L = max(L, P + 16)
        off = P + i * 977                     # 每条请求取不同片段，避免后缀重复
        suffix_ids = base_ids[off: off + (L - P)]
        if len(suffix_ids) < (L - P):         # 语料不够就回绕
            need = (L - P) - len(suffix_ids)
            suffix_ids = list(suffix_ids) + base_ids[P: P + need]
        prompt = prefix_text + tokenizer.decode(suffix_ids)

        O = int(r["output_length"])
        if ARGS.out_cap:
            O = min(O, ARGS.out_cap)
        O = max(O, 8)
        jobs.append({
            "idx": i,
            "timestamp": r.get("timestamp"),
            "hash_ids": r.get("hash_ids"),
            "target_in": L,
            "target_out": O,
            "prompt": prompt,
        })

    # ---- Poisson 到达时间 ----
    t, arrivals = 0.0, []
    for _ in jobs:
        t += rng.expovariate(1.0 / ARGS.mean_interval)
        arrivals.append(t)
    for j, a in zip(jobs, arrivals):
        j["arrival_s"] = a
    span = arrivals[-1]
    log(f"泊松到达       : λ = {1.0/ARGS.mean_interval:.4f} req/s "
        f"(平均间隔 {ARGS.mean_interval:.2f}s)，总到达跨度 {span:.1f}s")
    log(f"输入长度区间   : {min(j['target_in'] for j in jobs)} ~ "
        f"{max(j['target_in'] for j in jobs)} tokens")
    log(f"输出长度区间   : {min(j['target_out'] for j in jobs)} ~ "
        f"{max(j['target_out'] for j in jobs)} tokens")
    log(f"公共前缀       : {P} tokens（对应 trace 的 hash_ids[0] 共享前缀）")
    log("")

    # ---- 预热 ----
    for w in range(ARGS.warmup):
        st, ttft, lat, txt, uso, err = post_stream(
            "/v1/completions",
            {"model": ARGS.model, "prompt": "Hello", "max_tokens": 8,
             "temperature": 0.0, "stream": True,
             "stream_options": {"include_usage": True}},
            ARGS.timeout)
        log(f"[warmup {w+1}] status={st} ttft={ttft:.0f}ms latency={lat:.0f}ms err={err}")

    # ---- 并发按泊松时刻发送 ----
    results = [None] * len(jobs)
    results_lock = threading.Lock()
    t0 = time.perf_counter()
    done = [0]

    def worker(j):
        delay = j["arrival_s"] - (time.perf_counter() - t0)
        if delay > 0:
            time.sleep(delay)
        payload = {
            "model": ARGS.model,
            "prompt": j["prompt"],
            "max_tokens": j["target_out"],
            "temperature": 0.0,
            "ignore_eos": False,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        st, ttft, lat, txt, usage, err = post_stream("/v1/completions", payload, ARGS.timeout)
        pin = (usage or {}).get("prompt_tokens") or len(tokenizer.encode(j["prompt"]))
        pout = (usage or {}).get("completion_tokens") or len(tokenizer.encode(txt))
        rec = {
            "idx": j["idx"],
            "arrival_s": round(j["arrival_s"], 3),
            "input_tokens": pin,
            "target_input_tokens": j["target_in"],
            "output_tokens": pout,
            "target_output_tokens": j["target_out"],
            "status": "ok" if st == 200 else f"HTTP_{st}",
            "http_status": st,
            "ttft_ms": round(ttft, 1) if ttft else None,
            "latency_ms": round(lat, 1),
            "error": err,
        }
        with results_lock:
            results[j["idx"]] = rec
            done[0] += 1
            log(f"  [{done[0]:>2}/{len(jobs)}] req#{j['idx']:<2} "
                f"in={pin:<5} out={pout:<4} status={rec['status']:<7} "
                f"ttft={rec['ttft_ms']}ms  lat={rec['latency_ms']}ms")

    threads = [threading.Thread(target=worker, args=(j,), daemon=True) for j in jobs]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    wall = time.perf_counter() - t0

    ok = [r for r in results if r and r["http_status"] == 200]
    ttfts = [r["ttft_ms"] for r in ok if r["ttft_ms"]]
    lats = [r["latency_ms"] for r in ok]

    def pct(xs, p):
        if not xs:
            return 0.0
        xs = sorted(xs)
        k = min(len(xs) - 1, max(0, int(math.ceil(p / 100.0 * len(xs))) - 1))
        return xs[k]

    summary = {
        "trace_file": trace_path,
        "trace_total_records": len(recs),
        "sampled": len(jobs),
        "seed": ARGS.seed,
        "poisson_lambda_req_per_s": round(1.0 / ARGS.mean_interval, 4),
        "poisson_mean_interval_s": ARGS.mean_interval,
        "shared_prefix_tokens": P,
        "wall_time_s": round(wall, 2),
        "success": len(ok),
        "success_rate": round(len(ok) / len(jobs), 4) if jobs else 0.0,
        "ttft_ms": {
            "avg": round(statistics.mean(ttfts), 1) if ttfts else None,
            "p50": round(pct(ttfts, 50), 1) if ttfts else None,
            "p90": round(pct(ttfts, 90), 1) if ttfts else None,
            "min": round(min(ttfts), 1) if ttfts else None,
            "max": round(max(ttfts), 1) if ttfts else None,
        },
        "latency_ms": {
            "avg": round(statistics.mean(lats), 1) if lats else None,
            "p50": round(pct(lats, 50), 1) if lats else None,
            "p90": round(pct(lats, 90), 1) if lats else None,
        },
        "total_output_tokens": sum(r["output_tokens"] for r in ok),
        "output_throughput_tok_s": round(sum(r["output_tokens"] for r in ok) / wall, 2) if wall else None,
        "requests": results,
    }

    # ---- 抓取服务端 metrics（前缀缓存命中率等） ----
    try:
        conn = http.client.HTTPConnection(ARGS.host, ARGS.port, timeout=15)
        conn.request("GET", "/metrics")
        mtx = conn.getresponse().read().decode("utf-8", "replace")
        conn.close()
        with open(os.path.join(ARGS.out_dir, "sglang_metrics.txt"), "w", encoding="utf-8") as f:
            f.write(mtx)
        hits = [l for l in mtx.splitlines()
                if ("cache" in l.lower() or "prefix" in l.lower() or "radix" in l.lower())
                and not l.startswith("#")]
        summary["metrics_cache_lines"] = hits[:20]
    except Exception as e:
        summary["metrics_cache_lines"] = [f"metrics 抓取失败: {e}"]

    # ---- 落盘 ----
    jp = os.path.join(ARGS.out_dir, "benchmark_results.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    cp = os.path.join(ARGS.out_dir, "benchmark_results.csv")
    with open(cp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        for r in results:
            w.writerow(r)

    # ---- 屏幕上打印表格（截图2 用） ----
    W = 104
    log("")
    log("=" * W)
    log("Mooncake trace 采样 workload — 逐请求结果")
    log("=" * W)
    hdr = f"{'#':>3} {'arrive(s)':>9} {'in_tok':>7} {'out_tok':>7} {'status':>8} {'TTFT(ms)':>9} {'latency(ms)':>12}"
    log(hdr)
    log("-" * W)
    for r in results:
        log(f"{r['idx']:>3} {r['arrival_s']:>9.2f} {r['input_tokens']:>7} {r['output_tokens']:>7} "
            f"{r['status']:>8} {str(r['ttft_ms']):>9} {r['latency_ms']:>12.1f}")
    log("-" * W)
    log(f"采样来源 : Mooncake FAST'25  arxiv-trace/mooncake_trace.jsonl "
        f"(共 {len(recs)} 条，随机采样 {len(jobs)} 条, seed={ARGS.seed})")
    log(f"到达过程 : Poisson, λ={1.0/ARGS.mean_interval:.4f} req/s (平均间隔 {ARGS.mean_interval:.2f}s)")
    log(f"公共前缀 : {P} tokens（模拟 trace 中共享的 hash_ids[0]，触发 RadixCache 复用）")
    log(f"成功率   : {len(ok)}/{len(jobs)} = {summary['success_rate']*100:.1f}%   "
        f"总墙钟 {wall:.1f}s   输出吞吐 {summary['output_throughput_tok_s']} tok/s")
    log(f"TTFT(ms) : avg={summary['ttft_ms']['avg']}  p50={summary['ttft_ms']['p50']}  "
        f"p90={summary['ttft_ms']['p90']}  min={summary['ttft_ms']['min']}  max={summary['ttft_ms']['max']}")
    log(f"Latency  : avg={summary['latency_ms']['avg']}ms  p50={summary['latency_ms']['p50']}ms  "
        f"p90={summary['latency_ms']['p90']}ms")
    if summary.get("metrics_cache_lines"):
        log("服务端缓存相关指标：")
        for l in summary["metrics_cache_lines"][:8]:
            log("   " + l)
    log("=" * W)
    log(f"结果已保存: {jp}")
    log(f"          {cp}")

if __name__ == "__main__":
    main()
