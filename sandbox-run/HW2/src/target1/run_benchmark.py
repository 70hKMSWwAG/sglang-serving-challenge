#!/usr/bin/env python3
"""
HW2 任务一：测量 SGLang RadixCache 前缀缓存效果（对照实验）

两组负载，除"前缀能否复用"外，模型、输入长度、输出长度、请求顺序、并发数完全一致：
  - shared_prefix   : 32 条请求共享同一段长前缀（可命中 RadixCache）
  - dispersed_prefix: 32 条请求前缀各不相同（几乎无法命中）

统一设置：temperature=0, max_new_tokens=16, ignore_eos=true, sampling_seed=2026
接口：原生 /generate，提交 input_ids，流式响应（stream=true）
并发：最大并发 8；每组 32 条测量请求

流程（严格按挑战要求）：
  1. 首次实验前用短请求完成服务预热
  2. 每组测量前：等待已有请求结束 -> POST /flush_cache -> 确认成功
  3. 共享前缀组额外发送预热请求（把共享前缀写入 RadixCache），预热请求不计入结果
  4. 并发回放 32 条测量请求，逐请求记录 TTFT / TPOT / E2E / cached_tokens
  5. 输出 per_request.jsonl + summary.json

用法：
  python3 run_benchmark.py --group shared_prefix --run-id run-1
  python3 run_benchmark.py --group dispersed_prefix --run-id run-1
"""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

import aiohttp
import numpy as np
from transformers import AutoTokenizer

MODEL_PATH = "/workspace/models/Qwen3-0.6B"
DEFAULT_URL = "http://127.0.0.1:30000"

# 用于构造 synthetic prompt 的语料（技术文档风格，可重复拼接以控制长度）
CORPUS = (
    "Modern large language model serving systems must balance throughput and latency under "
    "limited accelerator memory. The scheduler batches incoming requests, the memory manager "
    "allocates key value cache pages, and the attention kernel reads cached states to avoid "
    "recomputation. Prefix sharing removes redundant prefill work when many prompts start with "
    "the same system instruction or document. Radix trees organize cached tokens by prefix so "
    "that lookup takes time proportional to the sequence length rather than the cache size. "
    "Batching, paging, and cache reuse together determine the end to end serving performance. "
)

# 每个请求各自的"用户问题"语料，用于构造互不相同的前缀/后缀
QUESTION_CORPUS = [
    "Summarize the tradeoff between batch size and latency in online inference.",
    "Explain how a radix tree enables automatic prefix sharing across requests.",
    "Describe the lifecycle of a key value cache entry from prefill to eviction.",
    "Compare continuous batching with static batching for conversational workloads.",
    "Why does the time to first token dominate perceived responsiveness?",
    "How does page sized memory allocation reduce external fragmentation?",
    "What metrics best characterize an inference server under Poisson arrivals?",
    "Illustrate how chunked prefill interacts with running decode batches.",
    "Discuss cache eviction policies when the working set exceeds memory.",
    "Analyze why memory bandwidth often limits decode phase throughput.",
]


def build_token_pool(tokenizer, n_tokens, seed):
    """
    用确定性方式生成长度为 n_tokens 的 token id 序列。
    不同 seed 会打乱语料句子顺序，因此生成的是"不同的文本"（保证分散前缀组前缀互不相同的同时，
    token 分布与统计特征保持一致）。返回的序列长度精确等于 n_tokens。
    """
    rng = np.random.default_rng(seed)
    sentences = QUESTION_CORPUS + [CORPUS]
    ids = []
    while len(ids) < n_tokens:
        order = rng.permutation(len(sentences))
        text = " ".join(sentences[i] for i in order) + " "
        ids.extend(tokenizer.encode(text))
    return ids[:n_tokens], rng


def build_requests(tokenizer, group, num_requests, input_len, prefix_len):
    """
    构造两组请求对应的 input_ids。
      shared_prefix   : 所有请求 = 同一段 prefix_len 的共享前缀 + 各自独立后缀
      dispersed_prefix: 每条请求 = 各自独立的 prefix_len 前缀 + 各自独立后缀
    两组输入长度严格相同，均为 input_len。
    """
    shared_prefix, _ = build_token_pool(tokenizer, prefix_len, seed=2026)
    reqs = []
    for k in range(num_requests):
        # 后缀：两组使用完全相同的后缀序列（seed 一致），保证"除前缀外输入一致"
        suffix_len = input_len - prefix_len
        suffix, _ = build_token_pool(tokenizer, suffix_len, seed=10_000 + k)
        if group == "shared_prefix":
            prefix = shared_prefix
        else:
            # 分散前缀：每条请求用不同语料起点生成互不相同的前缀（真实文本，非随机 token）
            prefix, _ = build_token_pool(tokenizer, prefix_len, seed=30_000 + k)
        ids = prefix + suffix
        assert len(ids) == input_len, f"input length mismatch: {len(ids)} != {input_len}"
        reqs.append(ids)

    # 自检：两组内部的输入重合度（分散组应几乎无重合，共享组应共享 prefix_len 个 token）
    def common_prefix_len(a, b):
        n = 0
        for x, y in zip(a, b):
            if x != y:
                break
            n += 1
        return n

    if len(reqs) >= 2:
        cp = [common_prefix_len(reqs[0], reqs[i]) for i in range(1, min(6, len(reqs)))]
        print(f"[self-check] {group}: 前几条请求与第 1 条请求的最长公共前缀长度 = {cp} "
              f"(共享组应≈{prefix_len}，分散组应≈0)")
    return reqs, shared_prefix


async def http_post_json(session, url, path, payload=None, timeout=120):
    async with session.post(f"{url}{path}", json=payload or {}, timeout=timeout) as resp:
        return resp.status, await resp.text()


async def wait_until_idle(session, url, tries=60, interval=1.0):
    """等待已有请求结束：反复调用 /flush_cache，只有在无运行请求时才会真正执行。"""
    for _ in range(tries):
        status, text = await http_post_json(session, url, "/flush_cache")
        # 成功时返回 200 + "Cache flushed."；有运行/等待请求时返回 400 + 失败原因
        if status == 200 and text.strip().startswith("Cache flushed."):
            return True, text.strip().splitlines()[0]
        await asyncio.sleep(interval)
    return False, "timeout waiting for idle"


async def wait_for_ready(session, url, tries=120, interval=1.0):
    for _ in range(tries):
        try:
            async with session.get(f"{url}/health_generate", timeout=30) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        await asyncio.sleep(interval)
    return False


async def stream_generate(session, url, input_ids, sampling_params, timeout=600):
    """发送一条流式 /generate 请求，返回逐请求指标。"""
    payload = {"input_ids": input_ids, "stream": True, "sampling_params": sampling_params}
    t_start = time.perf_counter()
    ttft = None
    t_last = None
    n_chunks = 0
    meta = {}
    status = None
    try:
        async with session.post(f"{url}/generate", json=payload, timeout=timeout) as resp:
            status = resp.status
            if status != 200:
                body = await resp.text()
                return {
                    "status": status, "error": body[:300], "ttft": None, "e2e": None,
                    "tpot": None, "prompt_tokens": None, "cached_tokens": None,
                    "completion_tokens": None, "prefill_tokens": None,
                    "server_e2e_latency": None, "n_chunks": 0,
                }
            async for raw_line in resp.content:
                line = raw_line.decode("utf-8", errors="ignore").strip()
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
                if ttft is None:
                    ttft = now - t_start
                t_last = now
                n_chunks += 1
                if obj.get("meta_info"):
                    meta = obj["meta_info"]
    except Exception as e:  # noqa: BLE001
        return {
            "status": status or -1, "error": repr(e)[:300], "ttft": ttft, "e2e": None,
            "tpot": None, "prompt_tokens": None, "cached_tokens": None,
            "completion_tokens": None, "prefill_tokens": None,
            "server_e2e_latency": None, "n_chunks": n_chunks,
        }

    e2e = (t_last - t_start) if t_last else None
    prompt_tokens = meta.get("prompt_tokens")
    cached_tokens = meta.get("cached_tokens")
    completion_tokens = meta.get("completion_tokens")
    prefill_tokens = (
        prompt_tokens - cached_tokens
        if (prompt_tokens is not None and cached_tokens is not None)
        else None
    )
    tpot = None
    if e2e is not None and ttft is not None and completion_tokens and completion_tokens > 1:
        tpot = (e2e - ttft) / (completion_tokens - 1)

    return {
        "status": status, "error": None, "ttft": ttft, "e2e": e2e, "tpot": tpot,
        "prompt_tokens": prompt_tokens, "cached_tokens": cached_tokens,
        "completion_tokens": completion_tokens, "prefill_tokens": prefill_tokens,
        "server_e2e_latency": meta.get("e2e_latency"), "n_chunks": n_chunks,
    }


def percentile(values, p):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = (len(vals) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


async def run_group(args):
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
    reqs, shared_prefix = build_requests(
        tokenizer, args.group, args.num_requests, args.input_len, args.prefix_len
    )
    sampling_params = {
        "temperature": 0,
        "max_new_tokens": args.output_len,
        "ignore_eos": True,
        "sampling_seed": 2026,
    }
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=600)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        ok = await wait_for_ready(session, args.url)
        if not ok:
            raise RuntimeError("server not ready")

        # ---------- 1) 服务预热（短请求，不计入结果） ----------
        if args.warmup:
            for _ in range(2):
                await stream_generate(
                    session, args.url, reqs[0][:32],
                    {"temperature": 0, "max_new_tokens": 4, "ignore_eos": True, "sampling_seed": 2026},
                )

        # ---------- 2) 等待空闲 + flush_cache 并确认成功 ----------
        idle_ok, idle_msg = await wait_until_idle(session, args.url)
        print(f"[flush] idle={idle_ok} msg={idle_msg!r}")
        if not idle_ok:
            raise RuntimeError("flush_cache failed: server not idle")

        # ---------- 3) 共享前缀组：发送预热请求，把共享前缀写入 RadixCache ----------
        if args.group == "shared_prefix" and args.warmup:
            r = await stream_generate(
                session, args.url, shared_prefix,
                {"temperature": 0, "max_new_tokens": 4, "ignore_eos": True, "sampling_seed": 2026},
            )
            print(f"[prefix-warmup] status={r['status']} prompt={r['prompt_tokens']} "
                  f"cached={r['cached_tokens']} (不计入结果)")

        # ---------- 4) 并发回放 32 条测量请求 ----------
        sem = asyncio.Semaphore(args.concurrency)

        async def worker(idx, ids):
            async with sem:
                res = await stream_generate(session, args.url, ids, sampling_params)
            res["index"] = idx
            res["input_len"] = len(ids)
            print(f"[{args.group}][{idx:02d}] status={res['status']} "
                  f"ttft={res['ttft']:.3f}s e2e={res['e2e']:.3f}s "
                  f"prompt={res['prompt_tokens']} cached={res['cached_tokens']} "
                  f"prefill={res['prefill_tokens']} out={res['completion_tokens']}"
                  if res["ttft"] else f"[{args.group}][{idx:02d}] FAILED {res.get('error')}")
            return res

        t0 = time.perf_counter()
        results = await asyncio.gather(*[worker(i, ids) for i, ids in enumerate(reqs)])
        wall = time.perf_counter() - t0

    # ---------- 5) 汇总 ----------
    ok_results = [r for r in results if r["status"] == 200 and r["e2e"] is not None]
    success_rate = len(ok_results) / len(results)
    total_prompt = sum(r["prompt_tokens"] or 0 for r in ok_results)
    total_cached = sum(r["cached_tokens"] or 0 for r in ok_results)
    total_prefill = sum(r["prefill_tokens"] or 0 for r in ok_results)
    total_output = sum(r["completion_tokens"] or 0 for r in ok_results)
    hit_rate = total_cached / total_prompt if total_prompt else 0.0

    def p(vals, q):
        return percentile(vals, q)

    ttfts = [r["ttft"] for r in ok_results]
    tpots = [r["tpot"] for r in ok_results]
    e2es = [r["e2e"] for r in ok_results]

    summary = {
        "group": args.group,
        "run_id": args.run_id,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "server_url": args.url,
        "model": MODEL_PATH,
        "config": {
            "num_requests": args.num_requests,
            "concurrency": args.concurrency,
            "input_len": args.input_len,
            "prefix_len": args.prefix_len,
            "max_new_tokens": args.output_len,
            "temperature": 0,
            "ignore_eos": True,
            "sampling_seed": 2026,
            "interface": "native /generate with input_ids, stream=true",
        },
        "success_rate": round(success_rate, 4),
        "num_success": len(ok_results),
        "num_total": len(results),
        "wall_clock_s": round(wall, 3),
        "request_throughput_rps": round(len(ok_results) / wall, 4) if wall else None,
        "output_token_throughput_tps": round(total_output / wall, 3) if wall else None,
        "total_prompt_tokens": total_prompt,
        "total_cached_tokens": total_cached,
        "total_actual_prefill_tokens": total_prefill,
        "cache_hit_rate": round(hit_rate, 4),
        "avg_cached_tokens_per_request": round(total_cached / len(ok_results), 2) if ok_results else None,
        "avg_actual_prefill_tokens_per_request": round(total_prefill / len(ok_results), 2) if ok_results else None,
        "ttft_p50_s": round(p(ttfts, 50), 4) if p(ttfts, 50) is not None else None,
        "ttft_p95_s": round(p(ttfts, 95), 4) if p(ttfts, 95) is not None else None,
        "tpot_p50_s": round(p(tpots, 50), 4) if p(tpots, 50) is not None else None,
        "tpot_p95_s": round(p(tpots, 95), 4) if p(tpots, 95) is not None else None,
        "e2e_p50_s": round(p(e2es, 50), 4) if p(e2es, 50) is not None else None,
        "e2e_p95_s": round(p(e2es, 95), 4) if p(e2es, 95) is not None else None,
    }

    outdir = Path(args.outdir) / args.group / args.run_id
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "per_request.jsonl", "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")
    with open(outdir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n===== SUMMARY =====")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nresults written to {outdir}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True, choices=["shared_prefix", "dispersed_prefix"])
    ap.add_argument("--run-id", default="run-1")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--num-requests", type=int, default=32)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--input-len", type=int, default=1024)
    ap.add_argument("--prefix-len", type=int, default=896)
    ap.add_argument("--output-len", type=int, default=16)
    ap.add_argument("--outdir", default="/workspace/HW2/results/target1")
    ap.add_argument("--no-warmup", dest="warmup", action="store_false")
    args = ap.parse_args()

    asyncio.run(run_group(args))


if __name__ == "__main__":
    main()
