#!/usr/bin/env python3
"""Send one OpenAI-compatible chat completion and save the JSON response."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def post(url: str, payload: dict, timeout: float = 60.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(url: str, timeout: float = 15.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:30000")
    ap.add_argument("--model", default="Qwen/Qwen3-0.6B")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    models = get(args.base.rstrip("/") + "/v1/models")
    t0 = time.perf_counter()
    chat = post(
        args.base.rstrip("/") + "/v1/chat/completions",
        {
            "model": args.model,
            "messages": [
                {
                    "role": "user",
                    "content": "What is the capital of France? Answer in one sentence. /no_think",
                }
            ],
            "max_tokens": 32,
            "temperature": 0,
        },
    )
    latency = time.perf_counter() - t0
    record = {
        "endpoint": "/v1/chat/completions",
        "models": models,
        "latency_s": latency,
        "response": chat,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    content = chat["choices"][0]["message"]["content"]
    print(f"status=ok latency={latency:.4f}s content={content[:120]}")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
