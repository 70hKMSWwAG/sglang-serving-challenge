"""Flush the RadixCache of all four SGLang backends and confirm success.

Call between experiment rounds, after all requests have finished. Retries
each backend a few times (flush_cache fails while requests are in flight).
"""

import argparse
import sys
import time

import httpx


def flush_one(client: httpx.Client, base: str, tries: int = 20) -> bool:
    """SGLang 0.5.14 answers POST /flush_cache with plain text, not JSON."""
    for _ in range(tries):
        try:
            resp = client.post(f"{base}/flush_cache")
            if resp.status_code != 200:
                time.sleep(2)
                continue
            text = resp.text.lower()
            try:
                body = resp.json()
                if body.get("status", "success") == "success":
                    return True
            except ValueError:
                pass
            if "flushed" in text or "success" in text:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backends", default="31000,31001,31002,31003")
    args = ap.parse_args()
    all_ok = True
    with httpx.Client(timeout=30) as client:
        for port in args.backends.split(","):
            base = f"http://127.0.0.1:{port.strip()}"
            ok = flush_one(client, base)
            print(f"{'OK' if ok else 'FAILED'}  {base}/flush_cache")
            all_ok = all_ok and ok
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
