#!/usr/bin/env python3
"""Write a compact 20-row Mooncake-like JSONL if the full trace is unavailable."""

from __future__ import annotations

import json
from pathlib import Path

ROWS = [
    {"timestamp": 0, "input_length": 2287, "output_length": 24, "hash_ids": [0, 42, 43, 44, 45]},
    {"timestamp": 0, "input_length": 913, "output_length": 32, "hash_ids": [0, 723]},
    {"timestamp": 3052, "input_length": 2007, "output_length": 28, "hash_ids": [0, 446, 447, 448]},
    {"timestamp": 3052, "input_length": 3119, "output_length": 20, "hash_ids": [74, 75, 76, 77, 78, 79, 80]},
    {"timestamp": 3052, "input_length": 3135, "output_length": 19, "hash_ids": [74, 75, 76, 77, 78, 126, 127]},
    {"timestamp": 6105, "input_length": 1048, "output_length": 26, "hash_ids": [0, 1039, 1040]},
    {"timestamp": 6105, "input_length": 3066, "output_length": 20, "hash_ids": [74, 75, 76, 77, 78, 1041]},
    {"timestamp": 9162, "input_length": 1475, "output_length": 32, "hash_ids": [0, 1093, 1094]},
    {"timestamp": 9162, "input_length": 1106, "output_length": 24, "hash_ids": [0, 1249, 1250]},
    {"timestamp": 12214, "input_length": 2033, "output_length": 32, "hash_ids": [0, 1259, 1260, 1261]},
    {"timestamp": 12214, "input_length": 1900, "output_length": 28, "hash_ids": [0, 1264, 1265, 1266]},
    {"timestamp": 12214, "input_length": 1065, "output_length": 32, "hash_ids": [0, 1324, 1325]},
    {"timestamp": 15267, "input_length": 897, "output_length": 32, "hash_ids": [0, 1394]},
    {"timestamp": 15267, "input_length": 932, "output_length": 32, "hash_ids": [0, 1723]},
    {"timestamp": 18320, "input_length": 897, "output_length": 16, "hash_ids": [0, 1795]},
    {"timestamp": 21373, "input_length": 2640, "output_length": 32, "hash_ids": [0, 1852, 1853, 1854, 1855, 1856]},
    {"timestamp": 24426, "input_length": 2127, "output_length": 32, "hash_ids": [0, 2013, 2014, 2015, 2016]},
    {"timestamp": 27482, "input_length": 1421, "output_length": 28, "hash_ids": [0, 2089, 2090]},
    {"timestamp": 27482, "input_length": 953, "output_length": 16, "hash_ids": [0, 2194]},
    {"timestamp": 30535, "input_length": 3235, "output_length": 29, "hash_ids": [74, 75, 76, 77, 78, 2618, 2619]},
]


def main() -> None:
    dest = Path(__file__).resolve().parents[1] / "data" / "mooncake_trace.sample.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(json.dumps(r) for r in ROWS) + "\n", encoding="utf-8")
    print("wrote", dest, "n=", len(ROWS))


if __name__ == "__main__":
    main()
