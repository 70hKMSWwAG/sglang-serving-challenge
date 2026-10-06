"""HW2 target 1: measure SGLang prefix cache reuse with two matched workloads.

Two groups of 32 measured requests each, both sent to the native /generate
endpoint with input_ids and streaming responses. Everything is identical
between the groups except whether the prompts can share a prefix:

  shared_prefix   all 32 requests start with the same 1024-token prefix
  dispersed_prefix every request has its own unrelated prefix

Run order per group:
  1. short warm-up request so the server is ready (never counted)
  2. wait for in-flight requests to drain, POST /flush_cache on the backend
  3. shared_prefix only: send the "cache warm-up" request(s) from the table so
     the shared prefix is resident in the RadixCache (never counted)
  4. replay the 32 measured requests with max concurrency 8

Sampling is deterministic: temperature=0, max_new_tokens=16, ignore_eos=true,
sampling_seed=2026.
"""

import argparse
import asyncio
import csv
import json
import os
import random
import statistics
import time

import httpx

TOKEN_BASE = 4096
TOKEN_SPAN = 60000
SHARED_PREFIX_TOKENS = 1024
SUFFIX_TOKENS = 128
MEASURED_REQUESTS = 32
MAX_CONCURRENCY = 8
MAX_NEW_TOKENS = 16


def make_prefix(rng: random.Random, n: int) -> list:
    return [rng.randrange(TOKEN_BASE, TOKEN_BASE + TOKEN_SPAN) for _ in range(n)]


def build_groups(seed: int = 2026):
    """Return {group_name: [input_ids, ...]} with identical lengths."""
    rng = random.Random(seed)
    shared = make_prefix(rng, SHARED_PREFIX_TOKENS)
    total = SHARED_PREFIX_TOKENS + SUFFIX_TOKENS

    shared_group, dispersed_group = [], []
    for _ in range(MEASURED_REQUESTS):
        suffix = make_prefix(rng, SUFFIX_TOKENS)
        shared_group.append(shared + suffix)
        dispersed_group.append(make_prefix(rng, total))
    return {"shared_prefix": shared_group, "dispersed_prefix": dispersed_group}


async def send_one(
    client: httpx.AsyncClient,
    url: str,
    input_ids: list,
    sem: asyncio.Semaphore,
    row: dict,
) -> None:
    payload = {
        "input_ids": input_ids,
        "sampling_params": {
            "temperature": 0.0,
            "max_new_tokens": MAX_NEW_TOKENS,
            "ignore_eos": True,
            "sampling_seed": 2026,
        },
        "stream": True,
    }
    async with sem:
        start = time.perf_counter()
        try:
            async with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                ttft = None
                cached = 0
                prompt_tokens = len(input_ids)
                output_tokens = 0
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    body = line[len("data:"):].strip()
                    if body == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(body)
                    except ValueError:
                        continue
                    meta = chunk.get("meta_info") or {}
                    if ttft is None and (chunk.get("text") or meta):
                        ttft = time.perf_counter() - start
                    if "cached_tokens" in meta:
                        cached = int(meta.get("cached_tokens") or 0)
                    if "prompt_tokens" in meta:
                        prompt_tokens = int(meta.get("prompt_tokens") or prompt_tokens)
                    if "completion_tokens" in meta:
                        output_tokens = int(meta.get("completion_tokens") or 0)
                end = time.perf_counter()
        except Exception as exc:  # noqa: BLE001 - record and keep going
            row.update(status="failed", error=repr(exc)[:200])
            return

    latency = end - start
    tpot = ((latency - ttft) / output_tokens) if (ttft and output_tokens) else 0.0
    row.update(
        status="success",
        input_tokens=len(input_ids),
        prompt_tokens=prompt_tokens,
        cached_tokens=cached,
        prefill_tokens=max(0, prompt_tokens - cached),
        output_tokens=output_tokens,
        ttft_s=round(ttft or 0.0, 6),
        tpot_s=round(tpot, 6),
        latency_s=round(latency, 6),
    )


def percentile(values, q):
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * q)))
    return ordered[idx]


async def run_group(client, url, name, groups, warm_shared: bool):
    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    # 1. short warm-up (not counted)
    await send_one(httpx.AsyncClient(timeout=httpx.Timeout(None)), url,
                   make_prefix(random.Random(0), 32), asyncio.Semaphore(1), {})
    # let everything drain
    await asyncio.sleep(1.0)

    # 2. flush the RadixCache
    resp = await client.post(url.rsplit("/generate", 1)[0] + "/flush_cache")
    flushed = resp.status_code == 200

    # 3. shared prefix group warms its shared prefix first (not counted)
    if warm_shared:
        warm_ids = groups["shared_prefix"][0]
        await send_one(httpx.AsyncClient(timeout=httpx.Timeout(None)), url,
                       warm_ids, asyncio.Semaphore(1), {})
        await asyncio.sleep(1.0)

    # 4. measured replay
    rows = [{"request_id": i} for i in range(len(groups[name]))]
    t0 = time.perf_counter()
    await asyncio.gather(*[
        send_one(client, url, ids, sem, rows[i])
        for i, ids in enumerate(groups[name])
    ])
    wall = time.perf_counter() - t0

    ok = [r for r in rows if r.get("status") == "success"]
    prefill = sum(r["prefill_tokens"] for r in ok)
    prompt = sum(r["prompt_tokens"] for r in ok)
    summary = {
        "group": name,
        "backend": url,
        "requests": len(rows),
        "successful": len(ok),
        "failed": len(rows) - len(ok),
        "max_concurrency": MAX_CONCURRENCY,
        "input_tokens_per_request": len(groups[name][0]),
        "max_new_tokens": MAX_NEW_TOKENS,
        "cache_flushed_before_run": flushed,
        "shared_prefix_warmup": warm_shared,
        "wall_time_s": round(wall, 3),
        "throughput_rps": round(len(ok) / wall, 3) if wall else 0.0,
        "cached_tokens_total": sum(r["cached_tokens"] for r in ok),
        "prompt_tokens_total": prompt,
        "actual_prefill_tokens": prefill,
        "cache_hit_rate": round(1 - prefill / prompt, 6) if prompt else 0.0,
        "ttft_s": {
            "p50": round(percentile([r["ttft_s"] for r in ok], 0.5), 6),
            "p95": round(percentile([r["ttft_s"] for r in ok], 0.95), 6),
        },
        "tpot_s": {
            "p50": round(percentile([r["tpot_s"] for r in ok], 0.5), 6),
            "p95": round(percentile([r["tpot_s"] for r in ok], 0.95), 6),
        },
        "latency_s": {
            "p50": round(percentile([r["latency_s"] for r in ok], 0.5), 6),
            "p95": round(percentile([r["latency_s"] for r in ok], 0.95), 6),
            "mean": round(statistics.fmean([r["latency_s"] for r in ok]), 6) if ok else 0.0,
        },
    }
    return rows, summary


async def main_async(args):
    groups = build_groups(args.seed)
    url = f"http://{args.host}:{args.port}/generate"
    out_root = args.output_dir
    os.makedirs(out_root, exist_ok=True)
    results = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
        for name in ("shared_prefix", "dispersed_prefix"):
            rows, summary = await run_group(
                client, url, name, groups, warm_shared=(name == "shared_prefix")
            )
            out_dir = os.path.join(out_root, name)
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "requests.csv"), "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
                writer.writeheader()
                writer.writerows(rows)
            with open(os.path.join(out_dir, "summary.json"), "w") as f:
                json.dump(summary, f, indent=2)
            results[name] = summary
            print(json.dumps(summary, indent=2))

    with open(os.path.join(out_root, "compare.json"), "w") as f:
        json.dump(results, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=31000)
    ap.add_argument("--output-dir", default="../results/target1")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
