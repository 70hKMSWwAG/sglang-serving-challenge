#!/usr/bin/env python3
"""HTTP/SSE generator for evaluating SGLang routing policies."""

import argparse
import asyncio
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import aiohttp


ROUTING_HEADERS = {
    "replica_id": "X-Ray-Replica-ID",
    "ray_node_id": "X-Ray-Node-ID",
    "backend": "X-SGLang-Backend",
}
FIXED_WORKLOAD_SHA256 = (
    "f154ba954e28ca9612257edf5deb0d5dfc6bf27fd0115a701e1f49e52df75b03"
)
ARTIFACT_NAMES = (
    "config.json",
    "warmups.csv",
    "requests.csv",
    "summary.json",
    "failure.json",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def routing_metadata(headers, require: bool) -> tuple[str, str, str, list[str]]:
    values = {name: headers.get(header, "") for name, header in ROUTING_HEADERS.items()}
    missing = [header for name, header in ROUTING_HEADERS.items() if not values[name]]
    if not require:
        missing = []
    return (
        values["replica_id"],
        values["ray_node_id"],
        values["backend"],
        missing,
    )


def parse_metadata(raw_items: list[str]) -> dict[str, str]:
    metadata = {}
    for raw in raw_items:
        if "=" not in raw:
            raise ValueError("--metadata must use KEY=VALUE")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("--metadata keys cannot be empty")
        metadata[key] = value
    return metadata


def prepare_output_dir(path: Path, overwrite: bool) -> None:
    existing = [name for name in ARTIFACT_NAMES if (path / name).exists()]
    if existing and not overwrite:
        names = ", ".join(existing)
        raise ValueError(
            f"output directory already contains run artifacts ({names}); "
            "choose a new directory or pass --overwrite"
        )
    path.mkdir(parents=True, exist_ok=True)
    if overwrite:
        for name in existing:
            (path / name).unlink()


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[min(index, len(ordered) - 1)]


def stats(values: list[float]) -> dict:
    return {
        "mean": statistics.fmean(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def load_workload(path: Path) -> tuple[list[dict], list[dict]]:
    with path.open("r", encoding="utf-8") as file:
        records = [json.loads(line) for line in file if line.strip()]
    warmups = [record for record in records if record["phase"] == "warmup"]
    measured = [record for record in records if record["phase"] == "measured"]
    if not warmups or not measured:
        raise ValueError("workload must contain warmup and measured records")
    if any(record.get("arrival_offset_s") is None for record in measured):
        raise ValueError("measured records need arrival_offset_s; run make_arrivals.py first")
    return warmups, measured


def build_config(args, warmups: list[dict], measured: list[dict]) -> dict:
    workload_sha256 = file_sha256(args.workload)
    return {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_name": args.run_name or args.policy,
        "client_policy": args.policy,
        "model": args.model,
        "router_name": args.router_name,
        "max_ongoing_requests": args.max_ongoing_requests,
        "base_url": args.base_url,
        "session_header": args.session_header,
        "max_in_flight": args.max_in_flight,
        "timeout_s": args.timeout,
        "token_base": args.token_base,
        "token_span": args.token_span,
        "token_salt": args.token_salt,
        "sampling_seed": 2026,
        "expected_replicas": args.expected_replicas,
        "expected_backends": args.expected_backends,
        "expected_nodes": args.expected_nodes,
        "require_routing_headers": args.require_routing_headers,
        "workload": str(args.workload.resolve()),
        "workload_sha256": workload_sha256,
        "expected_workload_sha256": args.expected_workload_sha256,
        "workload_verified": (
            args.expected_workload_sha256 is None
            or workload_sha256 == args.expected_workload_sha256
        ),
        "warmup_requests": len(warmups),
        "measured_requests": len(measured),
        "metadata": args.metadata,
        "command": [sys.executable, *sys.argv],
    }


class TokenBuilder:
    def __init__(self, token_base: int, token_span: int, salt: int) -> None:
        self.token_base = token_base
        self.token_span = token_span
        self.salt = salt
        self.blocks: dict[tuple[int, int], list[int]] = {}

    def block(self, hash_id: int, size: int) -> list[int]:
        key = (hash_id, size)
        if key not in self.blocks:
            tokens = []
            for position in range(size):
                payload = f"block:{self.salt}:{hash_id}:{position}".encode("ascii")
                value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
                tokens.append(self.token_base + value % self.token_span)
            self.blocks[key] = tokens
        return self.blocks[key]

    def suffix(self, request_id: str, size: int) -> list[int]:
        tokens = []
        for position in range(size):
            payload = f"suffix:{self.salt}:{request_id}:{position}".encode("ascii")
            value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")
            tokens.append(self.token_base + value % self.token_span)
        return tokens

    def input_ids(self, record: dict) -> list[int]:
        block_size = int(record["tokens_per_block"])
        tokens = []
        for hash_id in record["hash_ids"]:
            tokens.extend(self.block(int(hash_id), block_size))
        tokens.extend(self.suffix(str(record["request_id"]), int(record["suffix_tokens"])))
        expected = int(record["input_tokens"])
        if len(tokens) != expected:
            raise ValueError(f"constructed {len(tokens)} tokens, expected {expected}")
        return tokens


async def send_request(
    session: aiohttp.ClientSession,
    record: dict,
    args,
    tokens: TokenBuilder,
    run_started: float,
    semaphore: asyncio.Semaphore,
    scheduled: bool,
) -> dict:
    planned = float(record["arrival_offset_s"]) if scheduled else 0.0
    if scheduled:
        await asyncio.sleep(max(0.0, run_started + planned - time.perf_counter()))
    ready_at = time.perf_counter()
    target = args.base_url.rstrip("/")
    replica_id = ""
    node_id = ""
    backend = ""
    prompt_ids = tokens.input_ids(record)
    payload = {
        "input_ids": prompt_ids,
        "sampling_params": {
            "temperature": 0.0,
            "max_new_tokens": int(record["output_tokens"]),
            "min_new_tokens": int(record["output_tokens"]),
            "ignore_eos": True,
            "sampling_seed": 2026,
        },
        "stream": True,
    }

    async with semaphore:
        started = time.perf_counter()
        first_token_at = None
        last_token_at = None
        prompt_tokens = 0
        cached_tokens = 0
        final_output_ids = []
        finish_reason = ""
        status = 0
        error = ""
        try:
            headers = {
                args.session_header: str(record["prefix_family"]),
                "X-Workload-Request-ID": str(record["request_id"]),
                "X-Prefix-Family": str(record["prefix_family"]),
            }
            async with session.post(
                f"{target}/generate", json=payload, headers=headers
            ) as response:
                status = response.status
                replica_id, node_id, backend, missing_headers = routing_metadata(
                    response.headers, args.require_routing_headers
                )
                if missing_headers:
                    error = "missing required response headers: " + ", ".join(
                        missing_headers
                    )
                if status != 200:
                    error = (await response.text())[:500]
                elif not error:
                    async for raw_line in response.content:
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        chunk = json.loads(data)
                        meta = chunk.get("meta_info") or {}
                        if meta.get("finish_reason") is not None:
                            finish_reason = json.dumps(
                                meta["finish_reason"], ensure_ascii=True
                            )
                        output_ids = chunk.get("output_ids") or []
                        if not output_ids:
                            continue
                        now = time.perf_counter()
                        if first_token_at is None:
                            first_token_at = now
                            prompt_tokens = int(meta.get("prompt_tokens", len(prompt_ids)))
                            cached_tokens = int(meta.get("cached_tokens", 0))
                        last_token_at = now
                        final_output_ids = output_ids
        except Exception as exc:
            error = repr(exc)

        finished = time.perf_counter()
        generated = len(final_output_ids)
        ttft = None if first_token_at is None else first_token_at - started
        tpot = None
        if first_token_at is not None and last_token_at is not None and generated > 1:
            tpot = (last_token_at - first_token_at) / (generated - 1)
        return {
            "request_id": record["request_id"],
            "phase": record["phase"],
            "prefix_family": record["prefix_family"],
            "popularity_tier": record.get("popularity_tier", ""),
            "traffic_phase": record.get("traffic_phase", ""),
            "family_request_count": record.get("family_request_count", 0),
            "affinity_backend": record["affinity_backend"],
            "source_line": record["source_line"],
            "planned_send_s": planned,
            "actual_send_s": started - run_started,
            "dispatch_lag_s": started - run_started - planned if scheduled else 0.0,
            "client_queue_s": started - ready_at,
            "input_tokens": len(prompt_ids),
            "requested_output_tokens": int(record["output_tokens"]),
            "prompt_tokens": prompt_tokens,
            "cached_tokens": cached_tokens,
            "output_tokens": generated,
            "finish_reason": finish_reason,
            "status_code": status,
            "error": error,
            "ttft_s": ttft,
            "tpot_s": tpot,
            "latency_s": finished - started,
            "finished_s": finished - run_started,
            "replica_id": replica_id,
            "ray_node_id": node_id,
            "backend": backend,
        }


def token_distribution(rows: list[dict], key: str) -> dict:
    distribution = {}
    for row in rows:
        name = row[key]
        item = distribution.setdefault(
            name,
            {
                "requests": 0,
                "input_tokens": 0,
                "cached_tokens": 0,
                "requested_output_tokens": 0,
                "output_tokens": 0,
            },
        )
        item["requests"] += 1
        item["input_tokens"] += int(row["input_tokens"])
        item["cached_tokens"] += int(row["cached_tokens"])
        item["requested_output_tokens"] += int(row["requested_output_tokens"])
        item["output_tokens"] += int(row["output_tokens"])
    return dict(sorted(distribution.items()))


def subset_summary(rows: list[dict]) -> dict:
    successful = [row for row in rows if row["status_code"] == 200 and not row["error"]]
    prompt_total = sum(int(row["prompt_tokens"]) for row in successful)
    cached_total = sum(int(row["cached_tokens"]) for row in successful)

    def values(key: str) -> list[float]:
        return [float(row[key]) for row in successful if row[key] is not None]

    return {
        "requests": len(rows),
        "successful": len(successful),
        "cache_hit_rate": cached_total / prompt_total if prompt_total else 0.0,
        "ttft_s": stats(values("ttft_s")),
        "latency_s": stats(values("latency_s")),
        "backend_distribution": dict(
            sorted(Counter(row["backend"] for row in successful).items())
        ),
    }


def summarize(rows: list[dict], warmups: list[dict], elapsed: float, args) -> dict:
    successful = [row for row in rows if row["status_code"] == 200 and not row["error"]]
    incomplete = [
        row
        for row in successful
        if int(row["output_tokens"]) != int(row["requested_output_tokens"])
    ]

    def values(key: str) -> list[float]:
        return [float(row[key]) for row in successful if row[key] is not None]

    prompt_total = sum(int(row["prompt_tokens"]) for row in successful)
    cached_total = sum(int(row["cached_tokens"]) for row in successful)
    planned_duration = max(float(row["planned_send_s"]) for row in rows)
    warmup_ok = [row for row in warmups if row["status_code"] == 200 and not row["error"]]
    warmup_incomplete = [
        row
        for row in warmup_ok
        if int(row["output_tokens"]) != int(row["requested_output_tokens"])
    ]
    replica_distribution = dict(
        sorted(Counter(row["replica_id"] for row in successful).items())
    )
    node_distribution = dict(
        sorted(Counter(row["ray_node_id"] for row in successful).items())
    )
    backend_distribution = dict(
        sorted(Counter(row["backend"] for row in successful).items())
    )
    validation_errors = []
    observed = (
        ("replicas", len(replica_distribution), args.expected_replicas),
        ("Ray nodes", len(node_distribution), args.expected_nodes),
        ("SGLang backends", len(backend_distribution), args.expected_backends),
    )
    for label, actual, expected in observed:
        if expected is not None and expected > 0 and actual != expected:
            validation_errors.append(f"expected {expected} {label}, observed {actual}")
    return {
        "schema_version": 2,
        "run_name": args.run_name or args.policy,
        "policy": args.policy,
        "router_name": args.router_name,
        "max_ongoing_requests": args.max_ongoing_requests,
        "model": args.model,
        "workload_sha256": args.workload_sha256,
        "max_in_flight": args.max_in_flight,
        "token_base": args.token_base,
        "token_span": args.token_span,
        "token_salt": args.token_salt,
        "expected_replicas": args.expected_replicas,
        "expected_backends": args.expected_backends,
        "expected_nodes": args.expected_nodes,
        "requests": len(rows),
        "successful": len(successful),
        "failed": len(rows) - len(successful),
        "incomplete": len(incomplete),
        "warmup_successful": len(warmup_ok),
        "warmup_failed": len(warmups) - len(warmup_ok),
        "warmup_incomplete": len(warmup_incomplete),
        "validation_errors": validation_errors,
        "elapsed_s": elapsed,
        "planned_duration_s": planned_duration,
        "offered_rate_rps": (len(rows) - 1) / planned_duration if planned_duration else None,
        "throughput_rps": len(successful) / elapsed if elapsed else 0.0,
        "prompt_tokens_total": prompt_total,
        "cached_tokens_total": cached_total,
        "computed_prefill_tokens_total": prompt_total - cached_total,
        "cache_hit_rate": cached_total / prompt_total if prompt_total else 0.0,
        "ttft_s": stats(values("ttft_s")),
        "tpot_s": stats(values("tpot_s")),
        "latency_s": stats(values("latency_s")),
        "dispatch_lag_s": stats(values("dispatch_lag_s")),
        "client_queue_s": stats(values("client_queue_s")),
        "replica_distribution": replica_distribution,
        "node_distribution": node_distribution,
        "backend_distribution": backend_distribution,
        "backend_token_distribution": token_distribution(successful, "backend"),
        "warmup_replica_distribution": dict(
            sorted(Counter(row["replica_id"] for row in warmup_ok).items())
        ),
        "warmup_node_distribution": dict(
            sorted(Counter(row["ray_node_id"] for row in warmup_ok).items())
        ),
        "warmup_backend_distribution": dict(
            sorted(Counter(row["backend"] for row in warmup_ok).items())
        ),
        "traffic_phases": {
            phase: subset_summary([row for row in rows if row["traffic_phase"] == phase])
            for phase in dict.fromkeys(row["traffic_phase"] for row in rows)
        },
        "popularity_tiers": {
            tier: subset_summary(
                [row for row in rows if row["popularity_tier"] == tier]
            )
            for tier in dict.fromkeys(row["popularity_tier"] for row in rows)
        },
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


async def async_main(args) -> int:
    warmup_records, measured_records = load_workload(args.workload)
    config = build_config(args, warmup_records, measured_records)
    if not config["workload_verified"]:
        raise ValueError(
            "workload SHA-256 does not match the published HW2 workload: "
            f"expected {args.expected_workload_sha256}, "
            f"got {config['workload_sha256']}"
        )
    args.workload_sha256 = config["workload_sha256"]
    prepare_output_dir(args.output_dir, args.overwrite)
    (args.output_dir / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    connector = aiohttp.TCPConnector(limit=0)
    tokens = TokenBuilder(args.token_base, args.token_span, args.token_salt)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        warmup_rows = []
        for record in warmup_records:
            warmup_rows.append(
                await send_request(
                    session,
                    record,
                    args,
                    tokens,
                    time.perf_counter(),
                    asyncio.Semaphore(1),
                    scheduled=False,
                )
            )
        warmup_failed = [
            row
            for row in warmup_rows
            if row["status_code"] != 200
            or row["error"]
            or int(row["output_tokens"]) != int(row["requested_output_tokens"])
        ]
        if warmup_failed:
            write_csv(args.output_dir / "warmups.csv", warmup_rows)
            failure = {
                "stage": "warmup",
                "message": "one or more prefix warmup requests failed",
                "failed_request_ids": [row["request_id"] for row in warmup_failed],
            }
            (args.output_dir / "failure.json").write_text(
                json.dumps(failure, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            print(json.dumps(failure, indent=2, ensure_ascii=True))
            return 1

        run_started = time.perf_counter()
        semaphore = asyncio.Semaphore(args.max_in_flight)
        measured_rows = await asyncio.gather(
            *(
                send_request(
                    session,
                    record,
                    args,
                    tokens,
                    run_started,
                    semaphore,
                    scheduled=True,
                )
                for record in measured_records
            )
        )
        elapsed = time.perf_counter() - run_started

    measured_rows.sort(key=lambda row: int(row["request_id"]))
    write_csv(args.output_dir / "warmups.csv", warmup_rows)
    write_csv(args.output_dir / "requests.csv", measured_rows)
    summary = summarize(measured_rows, warmup_rows, elapsed, args)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    valid = not any(
        (
            summary["failed"],
            summary["incomplete"],
            summary["warmup_failed"],
            summary["warmup_incomplete"],
            summary["validation_errors"],
        )
    )
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay the fixed HW2 workload and record streaming metrics."
    )
    parser.add_argument(
        "--policy",
        choices=("serve",),
        required=True,
        help="send every request through the Ray Serve HTTP endpoint",
    )
    parser.add_argument(
        "--run-name",
        required=True,
        help="stable name for this configuration and run",
    )
    parser.add_argument("--workload", type=Path, required=True)
    parser.add_argument(
        "--expected-workload-sha256",
        default=FIXED_WORKLOAD_SHA256,
        help="expected fixed-workload digest",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--max-in-flight", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--token-base", type=int, default=4096)
    parser.add_argument("--token-span", type=int, default=60000)
    parser.add_argument("--token-salt", type=int, default=2026)
    parser.add_argument("--session-header", default="X-Session-Id")
    parser.add_argument("--model", default="Qwen/Qwen3-0.6B")
    parser.add_argument("--router-name", required=True)
    parser.add_argument("--max-ongoing-requests", type=int, required=True)
    parser.add_argument("--expected-replicas", type=int, default=4)
    parser.add_argument("--expected-backends", type=int, default=4)
    parser.add_argument("--expected-nodes", type=int, default=4)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace workload artifacts already present in the output directory",
    )
    parser.add_argument(
        "--allow-missing-routing-headers",
        dest="require_routing_headers",
        action="store_false",
        help="debug only: do not fail when Ray routing response headers are absent",
    )
    parser.set_defaults(require_routing_headers=True)
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="additional run metadata written to config.json; may be repeated",
    )
    args = parser.parse_args()

    if args.max_in_flight <= 0 or args.token_span <= 0 or args.timeout <= 0:
        parser.error("concurrency, timeout, and token span must be positive")
    if any(
        value < 0
        for value in (
            args.expected_replicas,
            args.expected_backends,
            args.expected_nodes,
        )
    ):
        parser.error("expected routing counts cannot be negative")
    if args.max_ongoing_requests <= 0:
        parser.error("--max-ongoing-requests must be positive")
    try:
        args.metadata = parse_metadata(args.metadata)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        return asyncio.run(async_main(args))
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
