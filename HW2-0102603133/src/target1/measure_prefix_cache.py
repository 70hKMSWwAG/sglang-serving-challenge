#!/usr/bin/env python3
"""Measure SGLang Radix Cache: shared prefix vs dispersed prefix.

Protocol:
  POST /generate with input_ids, stream=true
  sampling: temperature=0, max_new_tokens=16, ignore_eos=true, sampling_seed=2026
  32 requests / group, max concurrency 8
  warmup short request, then flush_cache before each group
  shared group: one prefix-only warmup (not counted)
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SHARED_PREFIX_LEN = 2048
UNIQUE_SUFFIX_LEN = 64
TOTAL_LEN = SHARED_PREFIX_LEN + UNIQUE_SUFFIX_LEN
N_REQ = 32
MAX_CONCURRENCY = 8
MAX_NEW = 16
SEED = 2026


def percentile(xs: List[float], p: float) -> float:
    if not xs:
        return float("nan")
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    k = (len(ys) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ys[int(k)]
    return ys[f] * (c - k) + ys[c] * (k - f)


def http_json(method: str, url: str, payload: Optional[dict] = None, timeout: float = 180.0):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if not raw:
            return {"status": resp.status}
        text = raw.decode("utf-8")
        if text.startswith("data:"):
            return {"_sse": text}
        return json.loads(text)


def flush_cache(base: str) -> dict:
    url = base.rstrip("/") + "/flush_cache"
    try:
        return http_json("POST", url, {})
    except urllib.error.HTTPError as e:
        return {"error": str(e), "code": e.code}


def short_warmup(base: str) -> None:
    payload = {
        "input_ids": list(range(10, 42)),
        "sampling_params": {
            "temperature": 0,
            "max_new_tokens": 4,
            "ignore_eos": True,
            "sampling_seed": SEED,
        },
        "stream": False,
    }
    http_json("POST", base.rstrip("/") + "/generate", payload)


def parse_sse(raw: str) -> List[dict]:
    events = []
    for block in raw.split("\n\n"):
        line = block.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            continue
        events.append(json.loads(data))
    return events


def generate_stream(base: str, input_ids: List[int]) -> Dict[str, Any]:
    payload = {
        "input_ids": input_ids,
        "sampling_params": {
            "temperature": 0.0,
            "max_new_tokens": MAX_NEW,
            "ignore_eos": True,
            "sampling_seed": SEED,
        },
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/generate",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    ttft = None
    last = None
    token_times: List[float] = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        buf = b""
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                part, buf = buf.split(b"\n\n", 1)
                line = part.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data_s = line[5:].strip()
                if data_s == "[DONE]":
                    continue
                ev = json.loads(data_s)
                now = time.perf_counter()
                if ttft is None:
                    ttft = now - t0
                token_times.append(now)
                last = ev
    e2e = time.perf_counter() - t0
    if last is None:
        raise RuntimeError("empty stream")
    meta = last.get("meta_info") or {}
    completion = int(meta.get("completion_tokens") or 0)
    if ttft is None:
        ttft = float(meta.get("ttft") or e2e)
    if completion >= 2:
        tpot = (e2e - ttft) / (completion - 1)
    elif completion == 1:
        tpot = 0.0
    else:
        tpot = float("nan")
    prompt_tokens = int(meta.get("prompt_tokens") or len(input_ids))
    cached = int(meta.get("cached_tokens") or 0)
    return {
        "status": "ok",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion,
        "cached_tokens": cached,
        "prefill_tokens": prompt_tokens - cached,
        "ttft_s": ttft,
        "tpot_s": tpot,
        "e2e_s": e2e,
        "finish_reason": meta.get("finish_reason"),
    }


def build_shared_inputs(n: int) -> Tuple[List[int], List[List[int]]]:
    prefix = [(i * 17 + 101) % 30000 + 16 for i in range(SHARED_PREFIX_LEN)]
    reqs = []
    for k in range(n):
        suffix = [40000 + k * UNIQUE_SUFFIX_LEN + j for j in range(UNIQUE_SUFFIX_LEN)]
        reqs.append(prefix + suffix)
    return prefix, reqs


def build_dispersed_inputs(n: int) -> List[List[int]]:
    reqs = []
    for k in range(n):
        first = 1000 + k
        rest = [((k + 1) * 10007 + j * 13) % 30000 + 16 for j in range(TOTAL_LEN - 1)]
        ids = [first] + rest
        assert len(ids) == TOTAL_LEN
        assert ids[0] != (reqs[0][0] if reqs else -1) or k == 0
        reqs.append(ids)
    firsts = [r[0] for r in reqs]
    assert len(set(firsts)) == n, "first tokens must be unique"
    return reqs


def run_group(
    name: str,
    base: str,
    inputs: List[List[int]],
    out_dir: Path,
    prefix_warmup: Optional[List[int]] = None,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[{name}] waiting previous requests, then flush_cache", flush=True)
    flushed = flush_cache(base)
    (out_dir / "flush_cache.json").write_text(
        json.dumps(flushed, indent=2), encoding="utf-8"
    )
    if flushed.get("success") is not True and "Cache flushed" not in json.dumps(flushed):
        print(f"[{name}] flush_cache response={flushed}", flush=True)
    if prefix_warmup is not None:
        print(f"[{name}] sending uncounted prefix warmup len={len(prefix_warmup)}", flush=True)
        payload = {
            "input_ids": prefix_warmup,
            "sampling_params": {
                "temperature": 0.0,
                "max_new_tokens": MAX_NEW,
                "ignore_eos": True,
                "sampling_seed": SEED,
            },
            "stream": False,
        }
        warm = http_json("POST", base.rstrip("/") + "/generate", payload)
        (out_dir / "prefix_warmup.json").write_text(
            json.dumps(warm, indent=2, default=str), encoding="utf-8"
        )

    records: List[Dict[str, Any]] = [{} for _ in inputs]
    sem_t0 = time.perf_counter()
    gate = threading.Semaphore(MAX_CONCURRENCY)

    def one(i: int, ids: List[int]) -> None:
        with gate:
            t_start = time.perf_counter()
            try:
                rec = generate_stream(base, ids)
            except Exception as exc:
                rec = {
                    "status": f"error:{exc}",
                    "prompt_tokens": len(ids),
                    "completion_tokens": 0,
                    "cached_tokens": 0,
                    "prefill_tokens": len(ids),
                    "ttft_s": float("nan"),
                    "tpot_s": float("nan"),
                    "e2e_s": time.perf_counter() - t_start,
                }
            rec["req_index"] = i
            rec["input_len"] = len(ids)
            rec["first_token"] = ids[0]
            records[i] = rec
            print(
                f"[{name}] req={i:02d} status={rec['status']} "
                f"cached={rec.get('cached_tokens')} prefill={rec.get('prefill_tokens')} "
                f"ttft={rec.get('ttft_s'):.4f} e2e={rec.get('e2e_s'):.4f}",
                flush=True,
            )

    t_group0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as ex:
        futs = [ex.submit(one, i, ids) for i, ids in enumerate(inputs)]
        for f in as_completed(futs):
            f.result()
    wall = time.perf_counter() - t_group0
    _ = sem_t0

    ok = [r for r in records if r.get("status") == "ok"]
    prompt_sum = sum(r.get("prompt_tokens", 0) for r in ok)
    cached_sum = sum(r.get("cached_tokens", 0) for r in ok)
    prefill_sum = sum(r.get("prefill_tokens", 0) for r in ok)
    completion_sum = sum(r.get("completion_tokens", 0) for r in ok)
    hit_rate = (cached_sum / prompt_sum) if prompt_sum else 0.0
    throughput = (prompt_sum + completion_sum) / wall if wall > 0 else 0.0

    def col(key: str) -> List[float]:
        return [float(r[key]) for r in ok if r.get(key) is not None and r[key] == r[key]]

    summary = {
        "workload": name,
        "n_requests": len(inputs),
        "n_success": len(ok),
        "success_rate": len(ok) / len(inputs) if inputs else 0.0,
        "max_concurrency": MAX_CONCURRENCY,
        "temperature": 0.0,
        "max_new_tokens": MAX_NEW,
        "ignore_eos": True,
        "sampling_seed": SEED,
        "input_len": TOTAL_LEN,
        "output_len": MAX_NEW,
        "wall_time_s": wall,
        "throughput_tokens_per_s": throughput,
        "cache_hit_rate": hit_rate,
        "sum_cached_tokens": cached_sum,
        "sum_prompt_tokens": prompt_sum,
        "sum_prefill_tokens": prefill_sum,
        "ttft_p50_s": percentile(col("ttft_s"), 0.50),
        "ttft_p95_s": percentile(col("ttft_s"), 0.95),
        "tpot_p50_s": percentile(col("tpot_s"), 0.50),
        "tpot_p95_s": percentile(col("tpot_s"), 0.95),
        "e2e_p50_s": percentile(col("e2e_s"), 0.50),
        "e2e_p95_s": percentile(col("e2e_s"), 0.95),
        "mean_ttft_s": statistics.mean(col("ttft_s")) if col("ttft_s") else float("nan"),
        "mean_tpot_s": statistics.mean(col("tpot_s")) if col("tpot_s") else float("nan"),
        "mean_e2e_s": statistics.mean(col("e2e_s")) if col("e2e_s") else float("nan"),
    }
    (out_dir / "per_request.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:30000")
    ap.add_argument("--results-root", required=True)
    args = ap.parse_args()
    root = Path(args.results_root)
    print("service warmup with short request", flush=True)
    short_warmup(args.base)

    prefix, shared_inputs = build_shared_inputs(N_REQ)
    assert all(len(x) == TOTAL_LEN for x in shared_inputs)
    shared = run_group(
        "shared_prefix",
        args.base,
        shared_inputs,
        root / "shared_prefix",
        prefix_warmup=prefix,
    )
    dispersed_inputs = build_dispersed_inputs(N_REQ)
    assert all(len(x) == TOTAL_LEN for x in dispersed_inputs)
    dispersed = run_group(
        "dispersed_prefix",
        args.base,
        dispersed_inputs,
        root / "dispersed_prefix",
        prefix_warmup=None,
    )
    table = {
        "shared_prefix": shared,
        "dispersed_prefix": dispersed,
        "checks": {
            "both_all_success": shared["n_success"] == N_REQ and dispersed["n_success"] == N_REQ,
            "same_input_len": shared["input_len"] == dispersed["input_len"] == TOTAL_LEN,
            "same_output_len": shared["output_len"] == dispersed["output_len"] == MAX_NEW,
            "shared_higher_hit_rate": shared["cache_hit_rate"] > dispersed["cache_hit_rate"],
            "shared_fewer_prefill": shared["sum_prefill_tokens"] < dispersed["sum_prefill_tokens"],
        },
    }
    (root / "comparison.json").write_text(
        json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(table["checks"], indent=2))
    print("shared hit={:.4f} prefill={}  dispersed hit={:.4f} prefill={}".format(
        shared["cache_hit_rate"],
        shared["sum_prefill_tokens"],
        dispersed["cache_hit_rate"],
        dispersed["sum_prefill_tokens"],
    ))


if __name__ == "__main__":
    main()
