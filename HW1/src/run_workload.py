"""Sample Mooncake trace, build synthetic prompts, send to SGLang with Poisson arrivals."""
import json, random, time, urllib.request, os
from concurrent.futures import ThreadPoolExecutor

BASE = os.environ.get("SGLANG_URL", "http://127.0.0.1:30000")
# Trace / output lookup: env var > repo-relative path > legacy ~/hw1 path (compat)
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACE = os.environ.get("MOONCAKE_TRACE") or next(
    (p for p in [os.path.join(_REPO, "results", "mooncake_trace.jsonl"),
                 os.path.join(_REPO, "..", "sandbox-run", "HW1", "data", "mooncake_trace.jsonl"),
                 os.path.expanduser("~/hw1/mooncake_trace.jsonl")] if os.path.exists(p)),
    os.path.join(_REPO, "results", "mooncake_trace.jsonl"))
OUT = os.environ.get("WORKLOAD_OUT") or os.path.join(_REPO, "results", "workload_results.jsonl")
N, LAMBDA, SEED, MAX_IN, MAX_OUT = 20, 0.5, 2026, 2048, 64

random.seed(SEED)
recs = []
for l in open(TRACE):
    try:
        recs.append(json.loads(l))
    except Exception:
        pass  # skip truncated line
recs = [r for r in recs if 890 <= r["input_length"] <= MAX_IN]
sample = random.sample(recs, N)

WORDS = ["the","model","cache","token","attention","prefix","radix","system","data","compute",
         "layer","memory","batch","request","server","stream","latency","throughput","kv","gpu"]
def make_prompt(n):
    return " ".join(WORDS[i % len(WORDS)] + str(i % 97) for i in range(n))

def send(idx, inp, out_len, arrival):
    prompt = make_prompt(inp)
    body = json.dumps({"text": prompt,
        "sampling_params": {"max_new_tokens": out_len, "temperature": 0, "ignore_eos": True},
        "stream": True}).encode()
    req = urllib.request.Request(BASE + "/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t_send = time.time(); ttft = None; n_out = 0
    with urllib.request.urlopen(req, timeout=1800) as resp:
        for line in resp:
            if line.startswith(b"data:"):
                chunk = line[5:].strip()
                if chunk == b"[DONE]": break
                d = json.loads(chunk)
                if d.get("text"):
                    n_out += 1
                    if ttft is None: ttft = time.time() - t_send
    lat = time.time() - t_send
    rec = {"idx": idx, "input_tokens": inp, "output_tokens": out_len,
           "arrival_offset_s": round(arrival, 3), "status": "ok",
           "ttft_s": round(ttft, 4) if ttft else None, "latency_s": round(lat, 4)}
    with open(OUT, "a") as f: f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)

open(OUT, "w").close()
gaps = [random.expovariate(LAMBDA) for _ in range(N)]
events, acc = [], 0.0
for i, r in enumerate(sample):
    acc += gaps[i]; events.append((acc, i, r))

def worker(ev):
    t, i, r = ev
    wait = t - (time.time() - T0)
    if wait > 0: time.sleep(wait)
    try:
        send(i, r["input_length"], min(r["output_length"], MAX_OUT), t)
    except Exception as e:
        rec = {"idx": i, "status": "error", "error": str(e)[:200]}
        with open(OUT, "a") as f: f.write(json.dumps(rec) + "\n")
        print(rec, flush=True)

T0 = time.time()
with ThreadPoolExecutor(max_workers=N) as ex:
    list(ex.map(worker, events))
print("DONE")
