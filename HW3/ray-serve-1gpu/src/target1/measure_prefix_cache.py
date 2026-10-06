#!/usr/bin/env python3
"""HW target1: measure SGLang prefix-cache effect (shared vs dispersed prefix).

Spec (challenge 2, task 1):
  * SGLang with Radix Cache ON, native /generate endpoint, input_ids, streaming.
  * Two workload groups, 32 measured requests each, max concurrency 8.
  * temperature=0, max_new_tokens=16, ignore_eos=true, sampling_seed=2026.
  * Shared-prefix group : input = 2048 shared prefix tokens + 64 unique suffix
    tokens (2112 in total); before measuring, send ONE warm-up request that
    contains the shared prefix (not counted in results).
  * Dispersed-prefix group: 2112 tokens per request, all tokens distinct across
    requests; no prefix warm-up.
  * Before EACH group: wait for in-flight requests, POST /flush_cache, verify.
  * Before the FIRST group only: service warm-up with short requests.

Per-request metrics (streaming):
  ttft_s   -- first SSE chunk latency
  tpot_s   -- (last_token_at - first_token_at) / (output_tokens - 1)
  latency_s-- end-to-end
  cached_tokens / prompt_tokens come from the final chunk meta_info.

Usage (see README.md):
  python measure_prefix_cache.py --base-url http://127.0.0.1:30000 \
      --output-dir ../../results/target1
"""

import argparse
import csv
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

# ----------------------------------------------------------------------------
# Fixed experimental parameters (challenge spec)
# ----------------------------------------------------------------------------
N_REQUESTS = 32
MAX_CONCURRENCY = 8
SHARED_PREFIX_LEN = 2048
SUFFIX_LEN = 64
INPUT_LEN = 2112  # dispersed group, and shared group total (2048 + 64)
MAX_NEW_TOKENS = 16
SAMPLING_SEED = 2026
SEED = 2026

SAMPLING_PARAMS = {
    "temperature": 0.0,
    "max_new_tokens": MAX_NEW_TOKENS,
    "ignore_eos": True,
    "sampling_seed": SAMPLING_SEED,
}


def http_post(base_url, path, payload, timeout=300.0):
    return requests.post(base_url + path, json=payload, timeout=timeout)


def wait_drained(base_url, timeout=120.0):
    """Best-effort drain wait.

    Every request in this script is sent synchronously, so by construction no
    request is in flight between groups; we still give the scheduler a couple
    of seconds to retire the last batch and confirm the server is healthy
    (v0.5.14 /get_server_info does not expose queue depth counters).
    """
    time.sleep(2.0)
    deadline = time.time() + timeout
    while time.time() < deadline:
        for path in ("/health", "/v1/models"):
            try:
                r = requests.get(base_url + path, timeout=10)
                if r.status_code < 500:
                    return True
            except Exception:
                pass
        time.sleep(1.0)
    return False


def flush_cache(base_url):
    r = http_post(base_url, "/flush_cache", {})
    if r.status_code != 200:
        raise RuntimeError(f"/flush_cache failed: HTTP {r.status_code}: {r.text[:200]}")
    return True


def generate_stream(base_url, input_ids, session=None):
    """POST /generate with stream=True; return per-request metric dict."""
    payload = {
        "input_ids": input_ids,
        "sampling_params": SAMPLING_PARAMS,
        "stream": True,
        "return_logprob": False,
    }
    s = session or requests
    started = time.perf_counter()
    first_at = None
    last_at = None
    n_text_chunks = 0
    meta = {}
    status = 0
    error = ""
    try:
        with s.post(
            base_url + "/generate", json=payload, stream=True, timeout=300.0
        ) as r:
            status = r.status_code
            r.raise_for_status()
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                body = line[len("data:") :].strip()
                if body == "[DONE]":
                    break
                now = time.perf_counter()
                try:
                    obj = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if "meta_info" in obj:
                    meta = obj["meta_info"]
                n_text_chunks += 1
                if first_at is None:
                    first_at = now
                last_at = now
    except Exception as exc:  # noqa: BLE001 - record and continue
        error = f"{type(exc).__name__}: {exc}"[:200]

    done_at = time.perf_counter()
    prompt_tokens = int(meta.get("prompt_tokens", len(input_ids)))
    cached_tokens = int(meta.get("cached_tokens", 0))
    completion_tokens = int(meta.get("completion_tokens", 0))
    ttft = (first_at - started) if first_at is not None else float("nan")
    e2e = (last_at - started) if last_at is not None else float("nan")
    tpot = float("nan")
    if first_at is not None and last_at is not None and completion_tokens > 1:
        tpot = (last_at - first_at) / (completion_tokens - 1)
    return {
        "prompt_tokens": prompt_tokens,
        "input_tokens": len(input_ids),
        "cached_tokens": cached_tokens,
        "output_tokens": completion_tokens,
        "text_chunks": n_text_chunks,
        "status_code": status,
        "error": error,
        "ttft_s": round(ttft, 6),
        "tpot_s": round(tpot, 6),
        "latency_s": round(e2e, 6),
        "finish_reason": meta.get("finish_reason", {}).get("type", "")
        if isinstance(meta.get("finish_reason"), dict)
        else meta.get("finish_reason", ""),
    }


# ----------------------------------------------------------------------------
# Token builders (seeded => reproducible)
# ----------------------------------------------------------------------------
def build_token_ids(vocab_size: int):
    """Return (shared_prefix, [suffixes], dispersed_requests).

    * shared_prefix: 2048 random token ids (the shared prefix).
    * suffixes: 32 disjoint 64-token suffix blocks (all tokens unique).
    * dispersed_requests: 32 blocks of 2112 tokens; ALL tokens across all
      blocks are distinct (a random permutation of the vocab, sliced).
    """
    rng = random.Random(SEED)

    # A single random permutation; slices of it never overlap => guaranteed
    # "all tokens distinct" for both the dispersed bodies and the suffixes.
    perm = list(range(vocab_size))
    rng.shuffle(perm)

    cursor = 0

    def take(n):
        nonlocal cursor
        block = perm[cursor : cursor + n]
        cursor += n
        return block

    shared_prefix = take(SHARED_PREFIX_LEN)
    suffixes = [take(SUFFIX_LEN) for _ in range(N_REQUESTS)]
    dispersed = [take(INPUT_LEN) for _ in range(N_REQUESTS)]
    # preheat request for the shared group: one normal-shaped request
    shared_preheat = shared_prefix + suffixes[0]
    shared_requests = [shared_prefix + suf for suf in suffixes]
    return shared_prefix, shared_preheat, shared_requests, dispersed


def pctl(values, q):
    vals = sorted(values)
    if not vals:
        return float("nan")
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def run_group(name, base_url, requests_inputs, out_dir, warmup_inputs=None):
    """One measured group: flush -> (optional warmup) -> 32 requests @ conc 8."""
    wait_drained(base_url)
    flush_cache(base_url)
    print(f"[{name}] cache flushed")

    preheat_rows = []
    if warmup_inputs:
        for i, ids in enumerate(warmup_inputs):
            row = generate_stream(base_url, ids)
            row.update({"group": name, "request_id": f"warmup-{i}"})
            preheat_rows.append(row)
            print(
                f"[{name}] warmup {i}: cached={row['cached_tokens']} "
                f"prompt={row['prompt_tokens']} status={row['status_code']}"
            )

    rows = []
    lock = threading.Lock()
    session = requests.Session()

    def one(i):
        row = generate_stream(base_url, requests_inputs[i], session=session)
        row.update({"group": name, "request_id": i})
        with lock:
            rows.append(row)
        print(
            f"[{name}] req {i:02d}: cached={row['cached_tokens']:5d} "
            f"prompt={row['prompt_tokens']} ttft={row['ttft_s']:.4f}s "
            f"tpot={row['tpot_s']:.5f} e2e={row['latency_s']:.4f}s"
        )
        return row

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as ex:
        list(ex.map(one, range(N_REQUESTS)))
    elapsed = time.perf_counter() - t0

    rows.sort(key=lambda r: r["request_id"])
    ok = [r for r in rows if r["status_code"] == 200 and r["error"] == ""]
    sum_prompt = sum(r["prompt_tokens"] for r in ok)
    sum_cached = sum(r["cached_tokens"] for r in ok)
    summary = {
        "group": name,
        "requests": N_REQUESTS,
        "max_concurrency": MAX_CONCURRENCY,
        "successful": len(ok),
        "failed": len(rows) - len(ok),
        "elapsed_s": round(elapsed, 4),
        "throughput_rps": round(len(ok) / elapsed, 4) if elapsed > 0 else None,
        "prompt_tokens_total": sum_prompt,
        "cached_tokens_total": sum_cached,
        "cache_hit_rate": round(sum_cached / sum_prompt, 6) if sum_prompt else None,
        "computed_prefill_tokens_total": sum_prompt - sum_cached,
        "ttft_s": {
            "p50": round(pctl([r["ttft_s"] for r in ok], 0.50), 6),
            "p95": round(pctl([r["ttft_s"] for r in ok], 0.95), 6),
        },
        "tpot_s": {
            "p50": round(pctl([r["tpot_s"] for r in ok], 0.50), 6),
            "p95": round(pctl([r["tpot_s"] for r in ok], 0.95), 6),
        },
        "latency_s": {
            "p50": round(pctl([r["latency_s"] for r in ok], 0.50), 6),
            "p95": round(pctl([r["latency_s"] for r in ok], 0.95), 6),
        },
        "config": {
            "input_len": INPUT_LEN,
            "shared_prefix_len": SHARED_PREFIX_LEN if name == "shared_prefix" else 0,
            "suffix_len": SUFFIX_LEN if name == "shared_prefix" else 0,
            "max_new_tokens": MAX_NEW_TOKENS,
            "temperature": 0.0,
            "ignore_eos": True,
            "sampling_seed": SAMPLING_SEED,
            "token_seed": SEED,
        },
    }

    out = Path(out_dir) / name
    out.mkdir(parents=True, exist_ok=True)
    run_dir = out / "run-1"
    run_dir.mkdir(exist_ok=True)
    if preheat_rows:
        with open(run_dir / "warmup.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(preheat_rows[0].keys()))
            w.writeheader()
            w.writerows(preheat_rows)
    with open(run_dir / "requests.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(run_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"[{name}] summary -> {run_dir/'summary.json'}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:30000")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--vocab-size", type=int, default=151936,
                    help="tokenizer vocab upper bound for random token ids")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")

    # 0. service ready + warm up with short requests (spec: first experiment)
    r = requests.get(base + "/v1/models", timeout=30)
    r.raise_for_status()
    print("service ready:", base)
    short = [[random.Random(7 + i).randrange(args.vocab_size) for _ in range(32)]
             for i in range(4)]
    for i, ids in enumerate(short):
        row = generate_stream(base, ids)
        print(f"service warmup {i}: status={row['status_code']} "
              f"out={row['output_tokens']}")

    shared_prefix, shared_preheat, shared_reqs, dispersed = build_token_ids(
        args.vocab_size
    )

    # 1. dispersed prefix group: no prefix warm-up
    run_group("dispersed_prefix", base, dispersed, args.output_dir)

    # 2. shared prefix group: ONE warm-up request containing the shared prefix
    run_group(
        "shared_prefix",
        base,
        shared_reqs,
        args.output_dir,
        warmup_inputs=[shared_preheat],
    )
    print("DONE")


if __name__ == "__main__":
    main()
