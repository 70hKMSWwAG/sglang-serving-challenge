#!/usr/bin/env python3
"""
HW3 target3: print the report's main table from official summary.json files.

Usage:
    python analyze.py <summary.json> [<summary.json> ...]

Each summary.json is produced by the course's run_workload.py (via
run_round.sh). The group label is taken from the grand-parent directory name,
e.g. results/target3/C_affinity/run-1/summary.json -> "C_affinity/run-1".

Main-table columns follow the assignment: success rate, throughput, cache hit
rate, actual prefill tokens, TTFT p50/p95, end-to-end latency p95, and the
request distribution over the four SGLang backends.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fmt, markdown_table  # noqa: E402


def load_summary(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def label_for(path: Path) -> str:
    # .../results/target3/<group>/run-N/summary.json
    return f"{path.parent.parent.name}/{path.parent.name}"


def dist_str(dist: dict) -> str:
    return ", ".join(f"{k}:{v}" for k, v in sorted(dist.items()))


def main(argv) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    headers = [
        "group/run",
        "success",
        "throughput (req/s)",
        "cache hit rate",
        "actual prefill tokens",
        "TTFT p50 (s)",
        "TTFT p95 (s)",
        "e2e p95 (s)",
        "backend distribution",
    ]
    rows = []
    for raw in argv[1:]:
        path = Path(raw)
        s = load_summary(path)
        rows.append(
            [
                label_for(path),
                f"{s['successful']}/{s['requests']}",
                fmt(s["throughput_rps"], 2),
                fmt(s["cache_hit_rate"]),
                fmt(s["computed_prefill_tokens_total"], 0),
                fmt(s["ttft_s"]["p50"]),
                fmt(s["ttft_s"]["p95"]),
                fmt(s["latency_s"]["p95"]),
                dist_str(s["backend_distribution"]),
            ]
        )
    print("# target3 main table (from official summary.json)\n")
    print(markdown_table(headers, rows))

    print("\n# per-group details\n")
    for raw in argv[1:]:
        path = Path(raw)
        s = load_summary(path)
        print(f"## {label_for(path)}")
        print(f"- router: {s['router_name']}, max_ongoing_requests: {s['max_ongoing_requests']}")
        print(f"- warmup: {s['warmup_successful']}/{s['warmup_successful'] + s['warmup_failed']}")
        print(f"- validation_errors: {s['validation_errors']}")
        print(f"- tpot_s p50/p95: {fmt(s['tpot_s']['p50'])} / {fmt(s['tpot_s']['p95'])}")
        print(f"- dispatch_lag_s p95: {fmt(s['dispatch_lag_s']['p95'])} | "
              f"client_queue_s p95: {fmt(s['client_queue_s']['p95'])}")
        print(f"- replica_distribution: {dist_str(s['replica_distribution'])}")
        print(f"- node_distribution: {dist_str(s['node_distribution'])}")
        phases = s.get("traffic_phases", {})
        for phase, sub in phases.items():
            print(
                f"- phase {phase}: n={sub['requests']} ok={sub['successful']} "
                f"hit_rate={fmt(sub['cache_hit_rate'])} "
                f"ttft_p95={fmt(sub['ttft_s']['p95'])} lat_p95={fmt(sub['latency_s']['p95'])}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
