#!/usr/bin/env python3
"""Validate the fixed HW2 routing workload before an experiment."""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


FIXED_WORKLOAD_SHA256 = (
    "f154ba954e28ca9612257edf5deb0d5dfc6bf27fd0115a701e1f49e52df75b03"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workload", type=Path)
    parser.add_argument("--families", type=int, default=64)
    parser.add_argument("--warmups", type=int, default=64)
    parser.add_argument("--measured", type=int, default=2048)
    parser.add_argument("--backends", type=int, default=4)
    parser.add_argument("--expected-sha256", default=FIXED_WORKLOAD_SHA256)
    args = parser.parse_args()

    with args.workload.open("r", encoding="utf-8") as file:
        records = [json.loads(line) for line in file if line.strip()]
    warmups = [record for record in records if record["phase"] == "warmup"]
    measured = [record for record in records if record["phase"] == "measured"]

    if len(warmups) != args.warmups or len(measured) != args.measured:
        raise ValueError(
            f"expected {args.warmups} warmups/{args.measured} measured, got "
            f"{len(warmups)}/{len(measured)}"
        )

    by_family = defaultdict(list)
    for record in records:
        by_family[record["prefix_family"]].append(record)
    if len(by_family) != args.families:
        raise ValueError(f"expected {args.families} families, got {len(by_family)}")

    warmup_families = Counter(record["prefix_family"] for record in warmups)
    if set(warmup_families.values()) != {1}:
        raise ValueError("each family must have exactly one warmup")

    request_ids = [int(record["request_id"]) for record in measured]
    if sorted(request_ids) != list(range(args.measured)):
        raise ValueError("measured request IDs must be unique and contiguous")

    arrivals = [record.get("arrival_offset_s") for record in measured]
    has_schedule = any(value is not None for value in arrivals)
    if has_schedule:
        if any(value is None for value in arrivals):
            raise ValueError("the arrival schedule is only partially populated")
        if arrivals != sorted(arrivals):
            raise ValueError("arrival offsets must be nondecreasing")

    for family, family_records in by_family.items():
        shared_blocks = int(family_records[0]["shared_prefix_blocks"])
        expected_prefix = family_records[0]["hash_ids"][:shared_blocks]
        for record in family_records:
            if record["hash_ids"][:shared_blocks] != expected_prefix:
                raise ValueError(f"family {family} does not share its declared prefix")
            expected_tokens = (
                len(record["hash_ids"]) * int(record["tokens_per_block"])
                + int(record["suffix_tokens"])
            )
            if int(record["input_tokens"]) != expected_tokens:
                raise ValueError(f"record {record['request_id']} has invalid input_tokens")

    family_routes = {
        family: int(family_records[0]["affinity_backend"])
        for family, family_records in by_family.items()
    }
    if any(route < 0 or route >= args.backends for route in family_routes.values()):
        raise ValueError("affinity_backend is outside the configured backend range")

    digest = sha256(args.workload)
    if args.expected_sha256 and digest != args.expected_sha256:
        raise ValueError(
            f"expected SHA-256 {args.expected_sha256}, got {digest}"
        )

    result = {
        "sha256": digest,
        "records": len(records),
        "families": len(by_family),
        "warmups": len(warmups),
        "measured": len(measured),
        "scheduled": has_schedule,
        "planned_duration_s": arrivals[-1] if has_schedule else None,
        "tier_families": dict(
            sorted(
                Counter(
                    family_records[0]["popularity_tier"]
                    for family_records in by_family.values()
                ).items()
            )
        ),
        "tier_requests": dict(
            sorted(Counter(record["popularity_tier"] for record in measured).items())
        ),
        "traffic_phases": dict(
            sorted(Counter(record.get("traffic_phase", "") for record in measured).items())
        ),
        "affinity_family_distribution": dict(
            sorted(Counter(family_routes.values()).items())
        ),
        "affinity_request_distribution": dict(
            sorted(Counter(record["affinity_backend"] for record in measured).items())
        ),
    }
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
