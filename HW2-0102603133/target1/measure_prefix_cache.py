"""HW2 Task 1: measure prefix cache effect in SGLang.
Two groups of 32 requests, max concurrency 8:
  - dispersed_prefix: each request has a distinct prefix
  - shared_prefix:    all requests share one long common prefix
sampling_seed=2026, temperature=0, max_new_tokens=16, ignore_eos=true,
native /generate with input_ids, streaming, radix cache enabled.
"""
import json, time, urllib.request, os, sys, random
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1:30000"
SEED = 2026
MAX_NEW = 16
CONCURRENCY = 8
N = 32
PREFIX_LEN = 256   # shared prefix tokens
SUFFIX_LEN = 256   # per-request unique tokens
RESULTS = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/hw2/results/default.jsonl")

random.seed(SEED)

def gen_tokens(n, seed_offset=0):
    rnd = random.Random(SEED + seed_offset)
    return [rnd.randint(1000, 50000) for _ in range(n)]

def warmup_short():
    body = json.dumps({"input_ids": [1, 2, 3, 4, 5],
                       "sampling_params": {"max_new_tokens": 4, "temperature": 0, "ignore_eos": True},
                       "stream": False}).encode()
    urllib.request.urlopen(urllib.request.Request(BASE + "/generate", data=body,
        headers={"Content-Type": "application/json"}), timeout=300).read()

def flush_cache():
    r = urllib.request.urlopen(urllib.request.Request(BASE + "/flush_cache", data=b""), timeout=300)
    return r.read().decode()

def send_stream(idx, input_ids):
    body = json.dumps({"input_ids": input_ids,
                       "sampling_params": {"max_new_tokens": MAX_NEW, "temperature": 0,
                                           "ignore_eos": True, "sampling_seed": SEED},
                       "stream": True}).encode()
    req = urllib.request.Request(BASE + "/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    ttft = None
    text_out = ""
    with urllib.request.urlopen(req, timeout=3600) as resp:
        for line in resp:
            line = line.strip()
            if not line:
                continue
            if line.startswith(b"data:"):
                line = line[5:].strip()
            if line == b"[DONE]":
                break
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("text"):
                if ttft is None:
                    ttft = time.time() - t0
                text_out = obj["text"]
            meta = obj.get("meta_info") or {}
            if meta.get("finish_reason"):
                e2e = meta.get("e2e_latency", time.time() - t0)
                return {"idx": idx, "status": "ok", "input_tokens": len(input_ids),
                        "output_tokens": meta.get("completion_tokens", MAX_NEW),
                        "ttft_s": round(ttft, 4) if ttft else round(e2e, 4),
                        "e2e_latency_s": round(e2e, 4),
                        "cached_tokens": (meta.get("cached_tokens", None))}
    return {"idx": idx, "status": "timeout"}

def run_group(name, make_requests, warmup_req=None):
    print(f"=== group {name}: warmup ===", flush=True)
    warmup_short()
    print(flush_cache(), flush=True)
    if warmup_req:
        send_stream(-1, warmup_req)  # prime the shared prefix, not counted
        print("shared-prefix warmup done", flush=True)
    t0 = time.time()
    recs = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        for rec in ex.map(lambda a: send_stream(*a), make_requests()):
            recs.append(rec)
            print(rec, flush=True)
    total = time.time() - t0
    ok = [r for r in recs if r["status"] == "ok"]
    summary = {"group": name, "n": len(recs), "ok": len(ok),
               "wall_s": round(total, 3),
               "throughput_req_s": round(len(ok) / total, 4),
               "sum_input_tokens": sum(r["input_tokens"] for r in ok),
               "sum_output_tokens": sum(r["output_tokens"] for r in ok)}
    outdir = os.path.dirname(RESULTS); os.makedirs(outdir, exist_ok=True)
    with open(RESULTS, "a") as f:
        for r in recs: f.write(json.dumps({"group": name, **r}) + "\n")
    return summary

def dispersed():
    # each request: unique prefix tokens (different offsets => no shared prefix)
    return [(i, [i * 100 + k for k in range(1, SUFFIX_LEN + 1)] + gen_tokens(PREFIX_LEN, i))
            for i in range(N)]

_shared = gen_tokens(PREFIX_LEN, 999999)  # one common prefix for all
def shared():
    return [(i, _shared + gen_tokens(SUFFIX_LEN, i)) for i in range(N)]

if __name__ == "__main__":
    summaries = []
    summaries.append(run_group("dispersed_prefix", dispersed))
    summaries.append(run_group("shared_prefix", shared, warmup_req=_shared))
    sp = os.path.join(os.path.dirname(RESULTS), "summary.json")
    json.dump(summaries, open(sp, "w"), indent=2)
    print(json.dumps(summaries, indent=2), flush=True)
    print("ALL DONE", flush=True)
