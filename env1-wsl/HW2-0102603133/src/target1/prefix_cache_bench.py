#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prefix_cache_bench.py —— 任务一：测量 SGLang 前缀缓存（Radix Cache）的效果

严格对齐第二次挑战任务书的三．任务一：
  * 原生 /generate 接口，传 input_ids，使用流式响应（stream=True）
  * 两组负载，每组 32 条测量请求，最大并发 8
  * 统一 temperature=0、max_new_tokens=16、ignore_eos=true、sampling_seed=2026
  * 首次实验前先用短请求完成服务预热
  * 每组测量前等待已有请求结束，调用 POST /flush_cache 并确认成功；
    共享前缀组再额外发送 1 条包含共享前缀的预热请求（预热请求不计入结果）
  * 除前缀能否复用外，两组的模型、输入/输出长度、请求顺序、并发数完全一致

两组输入结构（任务书表格）：
  共享前缀 : 2048 个 token 的共享前缀 + 64 个 token 的独立后缀          (= 2112)
  分散前缀 : 输入长度均为 2112 个 token，且首个 token 各不相同          (= 2112)
             测量前准备：不进行前缀预热

— 控制变量的处理（这是本实验的关键设计）—
任务书表格给出的两种结构如果照字面各造一份语料，两组的「内容」会不同，
于是「性能差异」就可能被「内容差异」污染。为把变量压到最小，分散前缀组构造为：

    共享组第 i 条  =  SHARED[0:2048]                  + SUFFIX[i]
    分散组第 i 条  =  [u_i] + SHARED[1:2048]          + SUFFIX[i]

其中 SHARED = base[0:2048]，SUFFIX[i] = base[2048+64i : 2112+64i]，
u_i 为 32 个两两互不相同、且不等于 SHARED[0] 的合法 token id。

于是两组：
  - 输入长度都是 2112；
  - 独立后缀 SUFFIX[i] 逐字节相同（请求顺序也相同）；
  - 承载共享前缀的那 2048 个 token 中，有 2047 个完全相同；
  - 唯一差别是「位置 0 的 token 两两不同」——RadixCache 是从根节点按 token
    逐位匹配的，位置 0 一旦不同，整条路径就没有公共可达节点，
    于是前缀复用率为 0。这正是任务书所要求的「除前缀能否复用外，其余一致」。

自变量因此被隔离为单一变量：**前缀能否被 RadixCache 复用**。

指标定义（与任务书一致）：
    缓存命中率        = sum(cached_tokens) / sum(prompt_tokens)
    实际 Prefill token 数 = sum(prompt_tokens - cached_tokens)
其中 prompt_tokens / cached_tokens 直接取自服务端返回的 meta_info，非客户端估算。

用法（在 WSL 内，用 SGLang 环境的 python）：
    source /mnt/d/first-task/work/env.sh
    $VENV/bin/python prefix_cache_bench.py --tag run-1 --order shared,dispersed
"""

import argparse
import http.client
import json
import math
import os
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# 统一采样参数（任务书硬性要求，不允许改）
SAMPLING = {
    "temperature": 0,
    "max_new_tokens": 16,
    "ignore_eos": True,
    "sampling_seed": 2026,
}

DEFAULT_N = 32           # 每组测量请求数
DEFAULT_CONC = 8         # 最大并发数
DEFAULT_PREFIX = 2048    # 共享前缀 token 数
DEFAULT_SUFFIX = 64      # 独立后缀 token 数


# --------------------------------------------------------------------------- 参数
def parse_args():
    p = argparse.ArgumentParser(description="任务一：SGLang 前缀缓存测量")
    p.add_argument("--host", default=os.environ.get("HOST", os.environ.get("SGL_HOST", "127.0.0.1")))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", os.environ.get("SGL_PORT", "30000"))))
    p.add_argument("--model-dir", default=os.environ.get("MODEL_DIR", ""),
                   help="含 tokenizer 的模型目录（用于构造 input_ids）")
    p.add_argument("--out-root", default=os.environ.get("HW2_RESD", ""),
                   help="results/target1 目录")
    p.add_argument("--server-log", default=os.environ.get("SRV_LOG", ""),
                   help="SGLang 服务端日志路径，用于截取本组的 Prefill 证据")
    p.add_argument("--n", type=int, default=DEFAULT_N, help="每组测量请求数")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONC, help="最大并发数")
    p.add_argument("--prefix-tokens", type=int, default=DEFAULT_PREFIX)
    p.add_argument("--suffix-tokens", type=int, default=DEFAULT_SUFFIX)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--order", default="shared,dispersed",
                   help="两组执行顺序，取值 shared,dispersed 或 dispersed,shared")
    p.add_argument("--tag", default="run-1", help="本次运行在 results 下的子目录名")
    p.add_argument("--timeout", type=float, default=1800.0, help="单请求超时（秒）")
    p.add_argument("--dry-run", action="store_true", help="只打印负载统计并退出")
    return p.parse_args()


ARGS = parse_args()
HOST, PORT = ARGS.host, ARGS.port
BASE = f"http://{HOST}:{PORT}"
if not ARGS.out_root:
    ARGS.out_root = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "results", "target1")

# 在途请求计数（用于「等待已有请求结束」）
_INFLIGHT = 0
_INFLIGHT_LOCK = threading.Lock()


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------------- 统计
def percentile(values, q):
    """线性插值分位数（与 numpy 默认的 'linear' 方法一致）。"""
    xs = sorted(v for v in values if v is not None and not math.isnan(v))
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return float(xs[0])
    pos = (len(xs) - 1) * (q / 100.0)
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(xs[int(pos)])
    return float(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo))


def fmt(x, nd=2):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x:.{nd}f}"


# --------------------------------------------------------------------------- 负载构造
CORPUS_WORDS = [
    "radix", "attention", "prefix", "cache", "scheduler", "tokenizer", "batch",
    "decode", "prefill", "kernel", "latency", "throughput", "memory", "worker",
    "queue", "stream", "reuse", "tree", "node", "shard", "topology", "vector",
    "mask", "softmax", "logit", "greedy", "sample", "sequence", "slot", "pool",
    "allocator", "eviction", "chunk", "window", "graph", "capture", "runtime",
    "pipeline", "protocol", "request", "response", "backend", "frontend", "model",
    "weight", "tensor", "operator", "session", "cluster", "instance",
]


def build_corpus_text(min_tokens):
    """构造一段确定性的合成语料，保证 tokenizer 编码后长度 > min_tokens。

    语料本身只是载体：实验关心的是 token 序列能否被前缀缓存复用，
    与文本语义无关。使用固定 seed，保证多次运行得到逐字节相同的序列。
    """
    rng = random.Random(2026)
    lines = []
    i = 0
    while True:
        w = [rng.choice(CORPUS_WORDS) for _ in range(6)]
        lines.append(
            f"Segment {i} examines how the {w[0]} layer interacts with the "
            f"{w[1]} stage, so that {w[2]} reuse and {w[3]} scheduling remain "
            f"stable under a {w[4]} workload with {w[5]} constraints."
        )
        i += 1
        # 每 200 行估一次长度，够了就退出（避免多算）
        if i % 200 == 0:
            text = "\n".join(lines)
            if len(text) // 4 > min_tokens:
                return text


def pick_distinct_first_tokens(tok, n, forbid):
    """取 n 个两两互不相同、且都不落在 forbid 里的合法「普通文本」token id。

    要求「不落在共享前缀内」是本实验刻意加的不变量：它保证分散组的首 token
    既不同于共享前缀的第 0 个 token（前缀必然无法复用），也不会与共享前缀的
    任何其它位置撞车，从而「两组唯一差别只在位置 0」这一说法不留歧义。

    候选按确定性顺序枚举：
      1) 常见英文单词（覆盖面广、构造快）；
      2) 词表中形如「单个小写 ASCII 字母词」的普通 token（排除特殊 token，
         它们的词表形态形如 <|...|>，不含纯字母）。
    两条路径都只产出普通文本 token，且结果与 tokenizer 版本一一对应、可复现。
    """
    forbid = set(forbid)
    out, seen = [], set()

    def take(tid):
        """接受一个候选；被拒时返回 False。"""
        if tid in seen or tid in forbid:
            return False
        seen.add(tid)
        out.append(tid)
        return True

    words = [
        "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
        "india", "juliet", "kilo", "lima", "mike", "november", "oscar", "papa",
        "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
        "xray", "yankee", "zulu", "anchor", "beacon", "cedar", "dune", "ember",
        "fjord", "granite", "harbor", "ivory", "jasper", "kelp", "larch", "mesa",
        "nimbus", "onyx", "prism", "quartz", "ridge", "slate", "tundra",
        "obelisk", "vellum", "zephyr", "cobalt", "basalt", "gossamer", "lattice",
        "quiver", "sable", "thicket", "umbra", "void", "wander", "xenon", "yarrow",
        "zodiac", "abacus", "bramble", "cinder", "dovetail", "emberly", "fathom",
        "gambit", "harrow", "inlet", "juniper", "kestrel", "loom", "marrow",
        "nettle", "ochre", "pumice", "quill", "rivet", "saffron", "tallow",
        "umber", "verdigris", "wicket", "yew", "zinc",
    ]
    for w in words:
        ids = tok.encode(" " + w, add_special_tokens=False)
        if ids and take(ids[0]) and len(out) == n:
            return out

    # 词表扫描：取纯小写 ASCII 字母 token（按 id 升序，保证确定性）
    for tokstr, tid in sorted(tok.get_vocab().items(), key=lambda kv: kv[1]):
        s = tokstr[1:] if tokstr.startswith("\u0120") else tokstr  # 去掉 BPE 空格前缀
        if s.isascii() and s.isalpha() and s.islower():
            if take(tid) and len(out) == n:
                return out

    # 兜底：用词表内合法 id 补齐（仍保证互不相同且不落在 forbid 内）
    k = 2000
    while len(out) < n:
        if take(k) and len(out) == n:
            return out
        k += 1
    return out[:n]


def build_workloads(tok, n, n_prefix, n_suffix, seed):
    need = n_prefix + n * n_suffix + 64
    corpus = build_corpus_text(int(need * 1.3) + 512)
    base = tok(corpus, add_special_tokens=False)["input_ids"]
    if len(base) < need:
        raise RuntimeError(f"语料 token 数不足：{len(base)} < {need}")

    shared = base[0:n_prefix]
    uniq_first = pick_distinct_first_tokens(tok, n, forbid=shared)

    shared_ids, disp_ids = [], []
    for i in range(n):
        suffix = base[n_prefix + i * n_suffix: n_prefix + (i + 1) * n_suffix]
        assert len(suffix) == n_suffix
        shared_ids.append(list(shared) + list(suffix))
        # 分散组：仅把位置 0 换成互不相同的 token，其余与共享组逐位相同
        disp_ids.append([uniq_first[i]] + list(shared[1:]) + list(suffix))

    # 共享前缀组的预热请求（2048 + 64），其后缀取自语料更靠后的一段，
    # 与 32 条测量请求的后缀都不重叠，避免预热顺带缓存了某个测量后缀。
    warm_suffix = base[n_prefix + n * n_suffix: n_prefix + n * n_suffix + n_suffix]
    shared_warmup = list(shared) + list(warm_suffix)

    for lst in shared_ids + disp_ids:
        assert len(lst) == n_prefix + n_suffix, len(lst)
    for lst in disp_ids:
        assert lst[0] not in shared, "分散组首 token 不应落在共享前缀内"
    assert len(set(x[0] for x in disp_ids)) == n, "分散组首 token 必须两两不同"
    assert len(set(shared_warmup)) > 0

    return {
        "shared_ids": shared_ids,
        "dispersed_ids": disp_ids,
        "shared_warmup": shared_warmup,
        "shared_prefix": list(shared),
        "corpus_tokens": len(base),
        "unique_first_tokens": uniq_first,
    }


# --------------------------------------------------------------------------- HTTP
def send_generate_stream(input_ids, timeout):
    """向 /generate 发一条流式请求，返回逐请求的测量记录。

    TTFT 定义为「首个携带第 1 个生成 token 的 SSE 分片到达」的时刻；
    TPOT = (端到端 - TTFT) / (生成 token 数 - 1)。
    """
    global _INFLIGHT
    rec = {
        "ok": False,
        "error": None,
        "ttft_ms": None,
        "tpot_ms": None,
        "e2e_ms": None,
        "prompt_tokens": None,
        "cached_tokens": None,
        "completion_tokens": None,
        "finish_reason": None,
        "n_chunks": 0,
    }
    payload = {
        "input_ids": input_ids,
        "sampling_params": dict(SAMPLING),
        "stream": True,
    }
    body = json.dumps(payload).encode("utf-8")
    conn = None
    t0 = time.perf_counter()
    with _INFLIGHT_LOCK:
        _INFLIGHT += 1
    try:
        conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
        conn.request(
            "POST", "/generate", body=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Connection": "close",
            },
        )
        resp = conn.getresponse()
        if resp.status != 200:
            err = resp.read(4096).decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {resp.status}: {err[:400]}")

        t_first = None
        n_out = 0
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            try:
                obj = json.loads(data.decode("utf-8"))
            except Exception:
                continue
            rec["n_chunks"] += 1
            meta = obj.get("meta_info") or {}
            if meta.get("cached_tokens") is not None:
                rec["cached_tokens"] = meta["cached_tokens"]
            if meta.get("prompt_tokens") is not None:
                rec["prompt_tokens"] = meta["prompt_tokens"]
            if meta.get("finish_reason"):
                rec["finish_reason"] = meta["finish_reason"]
            ct = meta.get("completion_tokens")
            if ct is not None:
                n_out = max(n_out, int(ct))
            txt = obj.get("text") or ""
            if t_first is None and (n_out >= 1 or txt):
                t_first = time.perf_counter()
        t_end = time.perf_counter()

        rec["e2e_ms"] = (t_end - t0) * 1000.0
        if t_first is not None:
            rec["ttft_ms"] = (t_first - t0) * 1000.0
        rec["completion_tokens"] = n_out
        if t_first is not None and n_out >= 2:
            rec["tpot_ms"] = (t_end - t_first) * 1000.0 / (n_out - 1)
        elif n_out == 1:
            rec["tpot_ms"] = 0.0
        rec["ok"] = (n_out > 0 and rec["prompt_tokens"] is not None)
        if not rec["ok"]:
            rec["error"] = "响应流结束但未获得有效 token 计数"
    except Exception as e:  # noqa: BLE001 —— 单条失败不应中断整组
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["e2e_ms"] = (time.perf_counter() - t0) * 1000.0
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        with _INFLIGHT_LOCK:
            _INFLIGHT -= 1
    return rec


def http_post(path, timeout=120.0):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        conn.request("POST", path, body=b"", headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        txt = r.read().decode("utf-8", "replace")
        return r.status, txt
    finally:
        conn.close()


def flush_cache():
    """POST /flush_cache 并确认成功（任务书要求）。"""
    st, txt = http_post("/flush_cache")
    ok = (st == 200 and "Cache flushed" in txt)
    return {"status": st, "body": txt.strip(), "success": ok}


def wait_idle(timeout=300.0, settle=3.0):
    """等待在途请求全部结束，再静置 settle 秒。"""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        with _INFLIGHT_LOCK:
            cur = _INFLIGHT
        if cur == 0:
            break
        time.sleep(0.2)
    time.sleep(settle)
    return cur == 0


def log_offset(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def log_slice(path, start, end):
    if start is None or end is None or end <= start:
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read(end - start)
        return data.decode("utf-8", "replace")
    except OSError:
        return ""


# --------------------------------------------------------------------------- 主流程
def summarize(group, records, wall_s, extra):
    ok = [r for r in records if r["ok"]]
    n = len(records)
    prompt_tok = sum(r["prompt_tokens"] or 0 for r in ok)
    cached_tok = sum(r["cached_tokens"] or 0 for r in ok)
    out_tok = sum(r["completion_tokens"] or 0 for r in ok)
    ttft = [r["ttft_ms"] for r in ok if r["ttft_ms"] is not None]
    tpot = [r["tpot_ms"] for r in ok if r["tpot_ms"] is not None]
    e2e = [r["e2e_ms"] for r in ok if r["e2e_ms"] is not None]

    s = {
        "group": group,
        "n_requested": n,
        "n_success": len(ok),
        "success_rate": (len(ok) / n) if n else 0.0,
        "wall_clock_s": wall_s,
        "request_throughput_rps": (len(ok) / wall_s) if wall_s else None,
        "output_throughput_tok_s": (out_tok / wall_s) if wall_s else None,
        "total_prompt_tokens": prompt_tok,
        "total_cached_tokens": cached_tok,
        "total_completion_tokens": out_tok,
        "cache_hit_rate": (cached_tok / prompt_tok) if prompt_tok else None,
        "actual_prefill_tokens": prompt_tok - cached_tok,
        "prefill_token_ratio": ((prompt_tok - cached_tok) / prompt_tok) if prompt_tok else None,
        "ttft_ms": {
            "p50": percentile(ttft, 50), "p95": percentile(ttft, 95),
            "avg": statistics.fmean(ttft) if ttft else None,
            "min": min(ttft) if ttft else None, "max": max(ttft) if ttft else None,
        },
        "tpot_ms": {
            "p50": percentile(tpot, 50), "p95": percentile(tpot, 95),
            "avg": statistics.fmean(tpot) if tpot else None,
            "min": min(tpot) if tpot else None, "max": max(tpot) if tpot else None,
        },
        "e2e_ms": {
            "p50": percentile(e2e, 50), "p95": percentile(e2e, 95),
            "avg": statistics.fmean(e2e) if e2e else None,
            "min": min(e2e) if e2e else None, "max": max(e2e) if e2e else None,
        },
    }
    s.update(extra)
    return s


def run_group(group, ids_list, out_root, tag, server_log, do_warmup, warmup_ids=None):
    """执行一组测量：等待空闲 → flush_cache → （可选）预热 → 32 条并发测量。

    结果落盘到 <out_root>/<group>/<tag>/，与任务书要求的交付目录一致
    （results/target1/{shared_prefix,dispersed_prefix}/run-N/）。
    """
    gdir = os.path.join(out_root, group, tag)
    os.makedirs(gdir, exist_ok=True)
    log(f"\n{'=' * 72}\n[组: {group}] 输出目录 {gdir}\n{'=' * 72}")

    # 1) 等待已有请求结束
    idle = wait_idle()
    log(f"  [1/5] 等待已有请求结束: {'OK' if idle else '超时（仍有在途请求）'}")

    # 2) flush_cache 并确认成功
    fc = flush_cache()
    log(f"  [2/5] POST /flush_cache → status={fc['status']} success={fc['success']} "
        f"body={fc['body'].splitlines()[0] if fc['body'] else ''!r}")
    with open(os.path.join(gdir, "flush_cache.json"), "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=2)
    if not fc["success"]:
        raise RuntimeError(f"flush_cache 未成功: {fc}")

    # 3) 共享前缀组：发送 1 条包含共享前缀的预热请求（不计入结果）
    warm_rec = None
    if do_warmup and warmup_ids is not None:
        log(f"  [3/5] 发送预热请求（含共享前缀，{len(warmup_ids)} tokens，不计入结果）")
        warm_rec = send_generate_stream(warmup_ids, ARGS.timeout)
        log(f"        预热结果 ok={warm_rec['ok']} prompt_tokens={warm_rec['prompt_tokens']} "
            f"cached_tokens={warm_rec['cached_tokens']} e2e={fmt(warm_rec['e2e_ms'], 1)}ms")
        with open(os.path.join(gdir, "warmup_request.json"), "w", encoding="utf-8") as f:
            json.dump(warm_rec, f, ensure_ascii=False, indent=2)
        if not warm_rec["ok"]:
            raise RuntimeError(f"共享前缀组的预热请求失败: {warm_rec['error']}")
    else:
        log("  [3/5] 本组不进行前缀预热（按任务书表格要求）")

    # 4) 32 条测量请求，最大并发 8，按序号顺序提交
    off0 = log_offset(server_log)
    log(f"  [4/5] 提交 {len(ids_list)} 条测量请求，最大并发 {ARGS.concurrency}")
    t0 = time.perf_counter()
    results = [None] * len(ids_list)
    with ThreadPoolExecutor(max_workers=ARGS.concurrency) as ex:
        futs = {}
        for i, ids in enumerate(ids_list):
            futs[ex.submit(send_generate_stream, ids, ARGS.timeout)] = i
        done = 0
        for fut, i in futs.items():
            results[i] = fut.result()
            done += 1
            if done % 8 == 0 or done == len(ids_list):
                log(f"        完成 {done}/{len(ids_list)}")
    wall = time.perf_counter() - t0
    off1 = log_offset(server_log)

    # 5) 落盘
    for i, r in enumerate(results):
        r["index"] = i
        r["group"] = group
        r["input_len"] = len(ids_list[i])
    jsonl = os.path.join(gdir, "requests.jsonl")
    with open(jsonl, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    sl = log_slice(server_log, off0, off1)
    if sl:
        with open(os.path.join(gdir, "server_log_slice.log"), "w", encoding="utf-8") as f:
            f.write(sl)

    summ = summarize(group, results, wall, {
        "warmup_request": warm_rec,
        "flush_cache": fc,
        "input_tokens_local": len(ids_list[0]) if ids_list else None,
        "concurrency": ARGS.concurrency,
        "sampling_params": dict(SAMPLING),
    })
    with open(os.path.join(gdir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=2)

    log(f"  [5/5] 结果已写入 {jsonl}")
    log(f"        成功率 {summ['n_success']}/{summ['n_requested']}  "
        f"墙钟 {summ['wall_clock_s']:.1f}s  "
        f"输出吞吐 {fmt(summ['output_throughput_tok_s'], 2)} tok/s")
    log(f"        缓存命中率 {fmt(100 * (summ['cache_hit_rate'] or 0), 2)}%  "
        f"实际 Prefill {summ['actual_prefill_tokens']} tokens "
        f"(总 prompt {summ['total_prompt_tokens']})")
    log(f"        TTFT p50/p95 = {fmt(summ['ttft_ms']['p50'], 1)}/{fmt(summ['ttft_ms']['p95'], 1)} ms  "
        f"TPOT p50/p95 = {fmt(summ['tpot_ms']['p50'], 1)}/{fmt(summ['tpot_ms']['p95'], 1)} ms  "
        f"E2E p50/p95 = {fmt(summ['e2e_ms']['p50'], 1)}/{fmt(summ['e2e_ms']['p95'], 1)} ms")
    return summ


def main():
    order = [s.strip() for s in ARGS.order.split(",") if s.strip()]
    for g in order:
        if g not in ("shared", "dispersed"):
            raise SystemExit(f"--order 只能包含 shared / dispersed，收到 {g!r}")

    out_root = os.path.abspath(ARGS.out_root)
    os.makedirs(out_root, exist_ok=True)
    # 交付目录：results/target1/<组名>/<tag>/（任务书规定的树形结构）
    for gname in ("shared_prefix", "dispersed_prefix"):
        os.makedirs(os.path.join(out_root, gname, ARGS.tag), exist_ok=True)

    log("=" * 72)
    log("任务一：SGLang 前缀缓存（Radix Cache）测量")
    log("=" * 72)
    log(f"  服务地址      : {BASE}")
    log(f"  模型目录      : {ARGS.model_dir or '(未指定)'}")
    log(f"  采样参数      : {SAMPLING}")
    log(f"  每组请求数    : {ARGS.n}    最大并发: {ARGS.concurrency}")
    log(f"  输入结构      : {ARGS.prefix_tokens} 共享前缀 + {ARGS.suffix_tokens} 独立后缀 = "
        f"{ARGS.prefix_tokens + ARGS.suffix_tokens} tokens")
    log(f"  执行顺序      : {order}")
    log(f"  结果目录      : {out_root}/<组名>/{ARGS.tag}")

    # 服务就绪检查
    conn = http.client.HTTPConnection(HOST, PORT, timeout=10)
    conn.request("GET", "/v1/models")
    r = conn.getresponse()
    models = json.loads(r.read().decode("utf-8"))
    conn.close()
    log(f"  可用模型      : {[m.get('id') for m in models.get('data', [])]}")

    # tokenizer
    from transformers import AutoTokenizer  # 延迟导入，--dry-run 之外都需要
    tok = AutoTokenizer.from_pretrained(ARGS.model_dir, trust_remote_code=True)
    log(f"  Tokenizer     : {type(tok).__name__}  vocab={tok.vocab_size}")

    wl = build_workloads(tok, ARGS.n, ARGS.prefix_tokens, ARGS.suffix_tokens, ARGS.seed)
    log(f"  语料 token 数 : {wl['corpus_tokens']}")
    log(f"  共享前缀长度  : {len(wl['shared_prefix'])}")
    log(f"  共享组请求长度: {sorted(set(len(x) for x in wl['shared_ids']))}")
    log(f"  分散组请求长度: {sorted(set(len(x) for x in wl['dispersed_ids']))}")
    log(f"  分散组首 token 去重后个数: {len(set(x[0] for x in wl['dispersed_ids']))}")

    meta = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_url": BASE,
        "model_dir": ARGS.model_dir,
        "sampling_params": dict(SAMPLING),
        "n_per_group": ARGS.n,
        "concurrency": ARGS.concurrency,
        "prefix_tokens": ARGS.prefix_tokens,
        "suffix_tokens": ARGS.suffix_tokens,
        "order": order,
        "tag": ARGS.tag,
        "corpus_tokens": wl["corpus_tokens"],
        "workload_design": (
            "shared   = SHARED[0:2048] + SUFFIX[i]; "
            "dispersed= [u_i] + SHARED[1:2048] + SUFFIX[i]; "
            "u_i 两两互异且 != SHARED[0]"
        ),
    }
    # run_meta.json 是「运行级」信息（与组别无关），两个组目录下各存一份，便于单独翻阅
    for gname in ("shared_prefix", "dispersed_prefix"):
        with open(os.path.join(out_root, gname, ARGS.tag, "run_meta.json"),
                  "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    if ARGS.dry_run:
        log("\n--dry-run：仅构造负载，不发送请求。")
        with open(os.path.join(out_root, "workload_sample.json"), "w", encoding="utf-8") as f:
            json.dump({
                "shared_ids_head": wl["shared_ids"][0][:16],
                "dispersed_ids_head": wl["dispersed_ids"][0][:16],
                "dispersed_first_tokens": [x[0] for x in wl["dispersed_ids"]],
            }, f, ensure_ascii=False, indent=2)
        return

    # 服务预热：一条短请求（任务书：首次实验前先用短请求完成服务预热）
    log("\n" + "-" * 72)
    log("服务预热：发送一条短请求")
    short = wl["shared_prefix"][:16]
    w = send_generate_stream(short, ARGS.timeout)
    log(f"  短请求 ok={w['ok']} prompt_tokens={w['prompt_tokens']} "
        f"cached_tokens={w['cached_tokens']} e2e={fmt(w['e2e_ms'], 1)}ms")
    if not w["ok"]:
        raise SystemExit(f"服务预热失败，终止：{w['error']}")
    for gname in ("shared_prefix", "dispersed_prefix"):
        with open(os.path.join(out_root, gname, ARGS.tag, "service_warmup.json"),
                  "w", encoding="utf-8") as f:
            json.dump(w, f, ensure_ascii=False, indent=2)

    summaries = {}
    for g in order:
        if g == "shared":
            summ = run_group("shared_prefix", wl["shared_ids"], out_root, ARGS.tag,
                             ARGS.server_log, True, wl["shared_warmup"])
        else:
            summ = run_group("dispersed_prefix", wl["dispersed_ids"], out_root, ARGS.tag,
                             ARGS.server_log, False, None)
        summaries[summ["group"]] = summ

    # 两组对照的合并汇总（运行级，两个组目录下各存一份）
    for gname in ("shared_prefix", "dispersed_prefix"):
        with open(os.path.join(out_root, gname, ARGS.tag, "run_summary.json"),
                  "w", encoding="utf-8") as f:
            json.dump(summaries, f, ensure_ascii=False, indent=2)

    # 控制台对照表
    log("\n" + "=" * 72)
    log(f"对照表（{ARGS.tag}，执行顺序 {' → '.join(order)}）")
    log("=" * 72)
    hdr = f"{'指标':<26}{'shared_prefix':>18}{'dispersed_prefix':>20}"
    log(hdr)
    log("-" * len(hdr))
    sp = summaries.get("shared_prefix")
    dp = summaries.get("dispersed_prefix")

    def row(name, f_sp, f_dp):
        log(f"{name:<26}{f_sp:>18}{f_dp:>20}")

    if sp and dp:
        row("成功率", f"{sp['n_success']}/{sp['n_requested']}",
            f"{dp['n_success']}/{dp['n_requested']}")
        row("吞吐量 (输出 tok/s)", fmt(sp["output_throughput_tok_s"]),
            fmt(dp["output_throughput_tok_s"]))
        row("吞吐量 (请求 req/s)", fmt(sp["request_throughput_rps"], 3),
            fmt(dp["request_throughput_rps"], 3))
        row("缓存命中率", fmt(100 * sp["cache_hit_rate"], 2) + "%",
            fmt(100 * dp["cache_hit_rate"], 2) + "%")
        row("实际 Prefill tokens", str(sp["actual_prefill_tokens"]),
            str(dp["actual_prefill_tokens"]))
        row("总 prompt tokens", str(sp["total_prompt_tokens"]),
            str(dp["total_prompt_tokens"]))
        row("TTFT p50 (ms)", fmt(sp["ttft_ms"]["p50"], 1), fmt(dp["ttft_ms"]["p50"], 1))
        row("TTFT p95 (ms)", fmt(sp["ttft_ms"]["p95"], 1), fmt(dp["ttft_ms"]["p95"], 1))
        row("TPOT p50 (ms)", fmt(sp["tpot_ms"]["p50"], 1), fmt(dp["tpot_ms"]["p50"], 1))
        row("TPOT p95 (ms)", fmt(sp["tpot_ms"]["p95"], 1), fmt(dp["tpot_ms"]["p95"], 1))
        row("端到端 p50 (ms)", fmt(sp["e2e_ms"]["p50"], 1), fmt(dp["e2e_ms"]["p50"], 1))
        row("端到端 p95 (ms)", fmt(sp["e2e_ms"]["p95"], 1), fmt(dp["e2e_ms"]["p95"], 1))
    log("=" * 72)


if __name__ == "__main__":
    main()
