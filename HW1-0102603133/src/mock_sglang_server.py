#!/usr/bin/env python3
"""Protocol-compatible SGLang stand-in for CPU-only verification.

Implements /v1/models, /v1/chat/completions, /generate, /flush_cache with a
RadixCache that records cached_tokens the same way SGLang v0.5.14 does after
match_prefix. Timing is a linear model of uncached prefill tokens plus decode
steps so prefix reuse shows up in TTFT, not as a GPU substitute.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

PAGE_SIZE = 1
PREFILL_S_PER_TOKEN = float(os.environ.get("MOCK_PREFILL_S_PER_TOKEN", "0.00004"))
DECODE_S_PER_TOKEN = float(os.environ.get("MOCK_DECODE_S_PER_TOKEN", "0.0012"))
BASE_OVERHEAD_S = float(os.environ.get("MOCK_BASE_OVERHEAD_S", "0.004"))
MODEL_NAME = os.environ.get("SGLANG_MODEL", "Qwen/Qwen3-0.6B")
HOST = os.environ.get("SGLANG_HOST", "0.0.0.0")
PORT = int(os.environ.get("SGLANG_PORT", "30000"))


class TreeNode:
    __slots__ = ("children",)

    def __init__(self) -> None:
        self.children: Dict[int, "TreeNode"] = {}


class RadixCache:
    def __init__(self, page_size: int = PAGE_SIZE) -> None:
        self.page_size = page_size
        self.root = TreeNode()
        self.lock = threading.Lock()

    def match_prefix(self, token_ids: List[int]) -> int:
        node = self.root
        matched = 0
        for tok in token_ids:
            child = node.children.get(tok)
            if child is None:
                break
            node = child
            matched += 1
        return (matched // self.page_size) * self.page_size

    def insert(self, token_ids: List[int]) -> None:
        node = self.root
        for tok in token_ids:
            child = node.children.get(tok)
            if child is None:
                child = TreeNode()
                node.children[tok] = child
            node = child

    def flush(self) -> None:
        self.root = TreeNode()


CACHE = RadixCache()
STATS = {
    "started_at": time.time(),
    "requests": 0,
    "generate_requests": 0,
    "flush_count": 0,
}
STATS_LOCK = threading.Lock()


def _json_bytes(payload: dict, status: int = 200) -> Tuple[int, bytes, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return status, body, "application/json"


def _chat_to_ids(messages) -> List[int]:
    text = ""
    if isinstance(messages, list):
        for m in messages:
            text += str(m.get("content", ""))
    else:
        text = str(messages)
    ids = [ord(c) % 32000 + 10 for c in text[:2048]]
    if not ids:
        ids = [151643]
    return ids


def _synthetic_decode(seed: int, n: int) -> List[int]:
    out = []
    x = seed & 0x7FFFFFFF
    for _ in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        out.append(100 + (x % 1000))
    return out


def _handle_generate(body: dict, stream: bool):
    input_ids = body.get("input_ids")
    text = body.get("text")
    sampling = body.get("sampling_params") or {}
    if input_ids is None:
        if text is None:
            raise ValueError("either input_ids or text is required")
        input_ids = [ord(c) % 32000 + 10 for c in str(text)]
        if not input_ids:
            input_ids = [151643]
    if isinstance(input_ids, list) and input_ids and isinstance(input_ids[0], list):
        input_ids = input_ids[0]
    input_ids = [int(x) for x in input_ids]
    max_new = int(sampling.get("max_new_tokens", 16))
    seed = int(sampling.get("sampling_seed", 2026))
    with CACHE.lock:
        cached = CACHE.match_prefix(input_ids)
    prompt_tokens = len(input_ids)
    uncached = max(prompt_tokens - cached, 0)
    prefill_s = BASE_OVERHEAD_S + uncached * PREFILL_S_PER_TOKEN
    decode_ids = _synthetic_decode(seed + prompt_tokens + cached, max_new)
    rid = body.get("rid") or uuid.uuid4().hex
    with STATS_LOCK:
        STATS["generate_requests"] += 1
        STATS["requests"] += 1
    return {
        "rid": rid,
        "input_ids": input_ids,
        "cached": cached,
        "prompt_tokens": prompt_tokens,
        "prefill_s": prefill_s,
        "decode_ids": decode_ids,
        "max_new": max_new,
        "stream": bool(body.get("stream", stream)),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        sys_stderr = os.environ.get("MOCK_QUIET")
        if sys_stderr:
            return
        super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str, extra=None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/v1/models", "/models"):
            payload = {
                "object": "list",
                "data": [
                    {
                        "id": MODEL_NAME,
                        "object": "model",
                        "created": int(STATS["started_at"]),
                        "owned_by": "sglang",
                    }
                ],
            }
            status, body, ctype = _json_bytes(payload)
            self._send(status, body, ctype)
            return
        if path in ("/health", "/health_generate"):
            status, body, ctype = _json_bytes({"status": "ok"})
            self._send(status, body, ctype)
            return
        if path == "/get_server_info":
            status, body, ctype = _json_bytes(
                {
                    "model_path": MODEL_NAME,
                    "radix_cache": True,
                    "page_size": PAGE_SIZE,
                    "version": "0.5.14-mock",
                    "stats": STATS,
                }
            )
            self._send(status, body, ctype)
            return
        self._send(404, b'{"error":"not found"}', "application/json")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except Exception as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        if path in ("/flush_cache", "/v1/flush_cache"):
            with CACHE.lock:
                CACHE.flush()
            with STATS_LOCK:
                STATS["flush_count"] += 1
            status, raw, ctype = _json_bytes({"message": "Cache flushed", "success": True})
            self._send(status, raw, ctype)
            return
        if path in ("/v1/chat/completions", "/chat/completions"):
            self._chat(body)
            return
        if path in ("/generate", "/v1/generate"):
            self._generate(body)
            return
        self._send(404, b'{"error":"not found"}', "application/json")

    def _chat(self, body: dict) -> None:
        messages = body.get("messages", [])
        max_tokens = int(body.get("max_tokens", body.get("max_new_tokens", 32)))
        stream = bool(body.get("stream", False))
        input_ids = _chat_to_ids(messages)
        gen_body = {
            "input_ids": input_ids,
            "sampling_params": {
                "max_new_tokens": max_tokens,
                "temperature": body.get("temperature", 0.7),
                "sampling_seed": body.get("seed", 2026),
            },
            "stream": stream,
        }
        job = _handle_generate(gen_body, stream)
        time.sleep(job["prefill_s"])
        text = "Paris is the capital of France. SGLang OpenAI-compatible mock reply."
        with CACHE.lock:
            CACHE.insert(job["input_ids"] + job["decode_ids"])
        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            chunk = {
                "id": "chatcmpl-" + job["rid"][:8],
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": MODEL_NAME,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": text},
                        "finish_reason": None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
            time.sleep(DECODE_S_PER_TOKEN)
            end = {
                "id": "chatcmpl-" + job["rid"][:8],
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": MODEL_NAME,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(end)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        payload = {
            "id": "chatcmpl-" + job["rid"][:8],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": job["prompt_tokens"],
                "completion_tokens": min(16, job["max_new"]),
                "total_tokens": job["prompt_tokens"] + min(16, job["max_new"]),
                "cached_tokens": job["cached"],
            },
        }
        status, raw, ctype = _json_bytes(payload)
        self._send(status, raw, ctype)

    def _generate(self, body: dict) -> None:
        try:
            job = _handle_generate(body, bool(body.get("stream", False)))
        except Exception as exc:
            self._send(400, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        t0 = time.perf_counter()
        time.sleep(job["prefill_s"])
        ttft = time.perf_counter() - t0
        if job["stream"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            acc_text = ""
            for i, tok in enumerate(job["decode_ids"], 1):
                time.sleep(DECODE_S_PER_TOKEN)
                acc_text += chr(65 + (tok % 26))
                meta = {
                    "id": job["rid"],
                    "finish_reason": None if i < job["max_new"] else {"type": "length"},
                    "prompt_tokens": job["prompt_tokens"],
                    "completion_tokens": i,
                    "cached_tokens": job["cached"],
                    "e2e_latency": time.perf_counter() - t0,
                    "ttft": ttft,
                }
                event = {"text": acc_text, "meta_info": meta, "output_ids": job["decode_ids"][:i]}
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            with CACHE.lock:
                CACHE.insert(job["input_ids"] + job["decode_ids"])
            return
        time.sleep(DECODE_S_PER_TOKEN * job["max_new"])
        e2e = time.perf_counter() - t0
        text = "".join(chr(65 + (t % 26)) for t in job["decode_ids"])
        with CACHE.lock:
            CACHE.insert(job["input_ids"] + job["decode_ids"])
        payload = {
            "text": text,
            "output_ids": job["decode_ids"],
            "meta_info": {
                "id": job["rid"],
                "finish_reason": {"type": "length"},
                "prompt_tokens": job["prompt_tokens"],
                "completion_tokens": job["max_new"],
                "cached_tokens": job["cached"],
                "e2e_latency": e2e,
                "ttft": ttft,
            },
        }
        status, raw, ctype = _json_bytes(payload)
        self._send(status, raw, ctype)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"The server is fired up and ready to roll! mock-sglang {MODEL_NAME} "
        f"http://{HOST}:{PORT} radix_cache=on page_size={PAGE_SIZE}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
