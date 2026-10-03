#!/usr/bin/env python3
"""Sample 10-30 Mooncake FAST'25 records and build a Poisson-arrival synthetic workload."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import List


def load_trace(path: Path, max_scan: int = 800) -> List[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= max_scan:
                break
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("input_length", 0) <= 0:
                continue
            rows.append(rec)
    return rows


def sample_records(rows: List[dict], n: int, seed: int) -> List[dict]:
    rng = random.Random(seed)
    eligible = [
        r
        for r in rows
        if 200 <= int(r["input_length"]) <= 4096 and 1 <= int(r["output_length"]) <= 128
    ]
    if len(eligible) < n:
        eligible = [r for r in rows if int(r["input_length"]) <= 8192]
    if len(eligible) < n:
        eligible = rows
    return rng.sample(eligible, n)


def poisson_arrivals(n: int, rate_per_s: float, seed: int) -> List[float]:
    rng = random.Random(seed + 17)
    t = 0.0
    times = []
    for _ in range(n):
        u = max(rng.random(), 1e-12)
        t += -math.log(u) / rate_per_s
        times.append(t)
    return times


def build_prompt(input_length: int, hash_ids, idx: int) -> str:
    target = max(32, min(int(input_length), 512))
    prefix = "SYSTEM: You are a concise assistant for LLM serving evaluation. "
    body = f"REQ{idx:02d} hashes={hash_ids[:8]} "
    filler = "alpha beta gamma delta epsilon zeta eta theta iota kappa "
    text = prefix + body
    while len(text.split()) < target:
        text += filler
    return " ".join(text.split()[:target])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--rate", type=float, default=4.0)
    args = ap.parse_args()
    rows = load_trace(Path(args.trace))
    sampled = sample_records(rows, args.n, args.seed)
    arrivals = poisson_arrivals(len(sampled), args.rate, args.seed)
    workload = []
    for i, (rec, t) in enumerate(zip(sampled, arrivals)):
        inp = min(int(rec["input_length"]), 512)
        out = min(max(int(rec["output_length"]), 8), 32)
        workload.append(
            {
                "req_id": f"mc-{i:02d}",
                "trace_timestamp_ms": rec.get("timestamp"),
                "poisson_arrival_s": round(t, 6),
                "input_length": inp,
                "output_length": out,
                "hash_ids": rec.get("hash_ids", [])[:16],
                "prompt": build_prompt(inp, rec.get("hash_ids", []), i),
            }
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(workload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(workload)} requests to {out}")


if __name__ == "__main__":
    main()
