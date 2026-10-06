"""Build the HW3 main table from the summary.json files of groups A/B1/B2/C/D.

Usage (from src/target3):

  python make_main_table.py \
    --run A=../../results/target3/A_default/summary.json \
    --run B1=../../results/target3/B_candidates/candidate-1/summary.json \
    --run B2=../../results/target3/B_candidates/candidate-2/summary.json \
    --run C=../../results/target3/C_affinity/summary.json \
    --run D=../../results/target3/D_improved/summary.json \
    --output ../../results/target3/main_table.csv

The course repo's compare_runs.py computes means and relative changes across
repeat runs; this script emits one row per group for the report's main table.
Keys follow the schema_version=2 layout of run_workload.py's summary.json.
"""

import argparse
import csv
import json
import os


def pct(metric: dict, q: float) -> float:
    return round(metric.get("p" + str(int(q * 100)), 0.0), 4)


def row_for(name: str, s: dict) -> dict:
    return {
        "group": name,
        "router": s.get("router_name", ""),
        "max_ongoing_requests": s.get("max_ongoing_requests", ""),
        "successful": s.get("successful", ""),
        "failed": s.get("failed", ""),
        "throughput_rps": round(s.get("throughput_rps", 0.0), 3),
        "cache_hit_rate": round(s.get("cache_hit_rate", 0.0), 4),
        "actual_prefill_tokens": s.get("computed_prefill_tokens_total", ""),
        "ttft_p50_s": pct(s.get("ttft_s", {}), 0.5),
        "ttft_p95_s": pct(s.get("ttft_s", {}), 0.95),
        "tpot_p95_s": pct(s.get("tpot_s", {}), 0.95),
        "latency_p50_s": pct(s.get("latency_s", {}), 0.5),
        "latency_p95_s": pct(s.get("latency_s", {}), 0.95),
        "dispatch_lag_p95_s": pct(s.get("dispatch_lag_s", {}), 0.95),
        "client_queue_p95_s": pct(s.get("client_queue_s", {}), 0.95),
        "backend_distribution": ";".join(
            f"{k}={v}" for k, v in sorted(s.get("backend_distribution", {}).items())
        ),
        "validation_errors": ";".join(s.get("validation_errors", [])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="NAME=path/to/summary.json")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    rows = []
    for item in args.run:
        name, _, path = item.partition("=")
        with open(path) as f:
            rows.append(row_for(name, json.load(f)))

    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {args.output} with {len(rows)} groups")


if __name__ == "__main__":
    main()
