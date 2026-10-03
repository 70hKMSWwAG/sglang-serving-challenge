#!/usr/bin/env python3
"""Replay a Poisson-arrival synthetic workload against SGLang /generate."""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List


def post_generate(base: str, prompt: str, max_new: int) -> Dict[str, Any]:
    payload = {
        "text": prompt,
        "sampling_params": {
            "max_new_tokens": max_new,
            "temperature": 0,
            "ignore_eos": True,
            "sampling_seed": 2026,
        },
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    e2e = time.perf_counter() - t0
    meta = body.get("meta_info") or {}
    return {
        "status": "ok",
        "input_tokens": meta.get("prompt_tokens"),
        "output_tokens": meta.get("completion_tokens"),
        "cached_tokens": meta.get("cached_tokens"),
        "ttft_s": meta.get("ttft"),
        "latency_s": meta.get("e2e_latency", e2e),
        "finish_reason": meta.get("finish_reason"),
        "text_preview": (body.get("text") or "")[:80],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:30000")
    ap.add_argument("--workload", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-inflight", type=int, default=4)
    args = ap.parse_args()
    workload = json.loads(Path(args.workload).read_text(encoding="utf-8"))
    start = time.perf_counter()
    results: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def run_one(item: dict) -> dict:
        wait = item["poisson_arrival_s"] - (time.perf_counter() - start)
        if wait > 0:
            time.sleep(wait)
        send_t = time.perf_counter() - start
        try:
            metrics = post_generate(args.base, item["prompt"], item["output_length"])
        except Exception as exc:
            metrics = {"status": f"error:{exc}"}
        rec = {
            "req_id": item["req_id"],
            "planned_arrival_s": item["poisson_arrival_s"],
            "actual_send_s": round(send_t, 6),
            "trace_input_length": item["input_length"],
            "trace_output_length": item["output_length"],
            **metrics,
        }
        with lock:
            results.append(rec)
        print(
            f"{rec['req_id']} status={rec.get('status')} "
            f"in={rec.get('input_tokens')} out={rec.get('output_tokens')} "
            f"ttft={rec.get('ttft_s')} lat={rec.get('latency_s')}",
            flush=True,
        )
        return rec

    with ThreadPoolExecutor(max_workers=args.max_inflight) as ex:
        futs = [ex.submit(run_one, item) for item in workload]
        for f in as_completed(futs):
            f.result()
    results.sort(key=lambda r: r["req_id"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in results if r.get("status") == "ok")
    print(f"done {ok}/{len(results)} ok -> {out}")


if __name__ == "__main__":
    main()
