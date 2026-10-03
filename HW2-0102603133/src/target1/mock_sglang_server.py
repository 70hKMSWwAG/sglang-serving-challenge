#!/usr/bin/env python3
"""Reuse the HW1 protocol-compatible server. See that file for semantics."""
import runpy
from pathlib import Path
import sys

CANDIDATES = [
    Path(__file__).resolve().parents[3] / "HW1-0102603133" / "src" / "mock_sglang_server.py",
    Path(__file__).resolve().parent / "server.py",
]
for p in CANDIDATES:
    if p.exists():
        sys.argv[0] = str(p)
        runpy.run_path(str(p), run_name="__main__")
        raise SystemExit(0)
raise SystemExit("mock_sglang_server.py not found")
