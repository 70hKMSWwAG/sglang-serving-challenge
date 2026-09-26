#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 侧预取：把 WSL 构建/运行所需的一切大文件先下到 D:\first-task\work\
目的：WSL 内 GitHub 很可能被 Watt Toolkit 劫持（hosts -> 127.0.0.1）或 TLS 受阻，
      预先落地后 WSL 侧完全离线可用。
"""
import json, os, sys, time, urllib.request, urllib.error

ROOT = r"D:\first-task\work"
DATA = os.path.join(ROOT, "data")
MODELS = os.path.join(ROOT, "models")
os.makedirs(DATA, exist_ok=True)
os.makedirs(MODELS, exist_ok=True)

MIRRORS = ["", "https://gh-proxy.com/", "https://gh.ddlc.top/"]

def log(*a): print(*a, flush=True)

def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())

def download(url, out, min_size=1024, retries=3):
    if os.path.isfile(out) and os.path.getsize(out) >= min_size:
        log(f"  [已存在] {os.path.basename(out)}  {os.path.getsize(out)/1e6:.1f} MB")
        return True
    for attempt in range(retries):
        for m in MIRRORS:
            u = m + url if m else url
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "curl/8"})
                t0 = time.time()
                with urllib.request.urlopen(req, timeout=180) as r, open(out + ".part", "wb") as f:
                    total = int(r.headers.get("Content-Length") or 0)
                    got = 0
                    while True:
                        b = r.read(1 << 20)
                        if not b:
                            break
                        f.write(b); got += len(b)
                        if total and got % (20 << 20) < (1 << 20):
                            log(f"     {got/1e6:.0f}/{total/1e6:.0f} MB  {got/1e6/max(time.time()-t0,1e-9):.1f} MB/s")
                if os.path.getsize(out + ".part") >= min_size:
                    os.replace(out + ".part", out)
                    log(f"  ✓ {os.path.basename(out)}  {os.path.getsize(out)/1e6:.1f} MB  "
                        f"({time.time()-t0:.0f}s)")
                    return True
                log(f"  ✗ 过小，换通道重试: {u}")
            except Exception as e:
                log(f"  ✗ {type(e).__name__}: {str(e)[:90]}  <- {u[:90]}")
        time.sleep(2)
    return False

# ---------------------------------------------------------------- 1. Mooncake trace
log("=" * 70); log("[1/4] Mooncake FAST'25 trace")
download("https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/"
         "FAST25-release/arxiv-trace/mooncake_trace.jsonl",
         os.path.join(DATA, "mooncake_trace.jsonl"), min_size=100000)

# ---------------------------------------------------------------- 2. SGLang v0.5.14 源码
log("=" * 70); log("[2/4] SGLang v0.5.14 源码快照")
tar = os.path.join(DATA, "sglang-v0.5.14.tar.gz")
download("https://codeload.github.com/sgl-project/sglang/tar.gz/refs/tags/v0.5.14",
         tar, min_size=5_000_000)
download("https://github.com/sgl-project/sglang/archive/refs/tags/v0.5.14.tar.gz", tar,
         min_size=5_000_000)

# ---------------------------------------------------------------- 3. CPython 3.12 standalone
log("=" * 70); log("[3/4] standalone CPython 3.12 (python-build-standalone)")
cp_out = os.path.join(DATA, "cpython-3.12-linux-x86_64.tar.gz")
if not (os.path.isfile(cp_out) and os.path.getsize(cp_out) > 5_000_000):
    try:
        rel = get_json("https://api.github.com/repos/astral-sh/"
                       "python-build-standalone/releases/latest")
        assets = [a["name"] for a in rel["assets"]]
        cand = [a for a in assets
                if a.startswith("cpython-3.12")
                and "x86_64-unknown-linux-gnu-install_only" in a
                and a.endswith(".tar.gz")]
        log(f"  候选: {cand}")
        if cand:
            tag = rel["tag_name"]
            name = sorted(cand)[-1]
            url = (f"https://github.com/astral-sh/python-build-standalone/releases/"
                   f"download/{tag}/{name}")
            log(f"  选择: {name}  ({tag})")
            download(url, cp_out, min_size=5_000_000)
            with open(os.path.join(DATA, "cpython_asset_name.txt"), "w") as f:
                f.write(name)
    except Exception as e:
        log(f"  ✗ 查询失败: {e}")
else:
    log("  [已存在] cpython-3.12-linux-x86_64.tar.gz")

# ---------------------------------------------------------------- 4. 模型 Qwen3-0.6B
log("=" * 70); log("[4/4] Qwen/Qwen3-0.6B 模型权重 (hf-mirror.com)")
DEST = os.path.join(MODELS, "Qwen3-0.6B")
os.makedirs(DEST, exist_ok=True)
HF = "https://hf-mirror.com"
try:
    info = get_json(f"{HF}/api/models/Qwen/Qwen3-0.6B")
    files = [s["rfilename"] for s in info.get("siblings", [])]
    log(f"  远端文件 {len(files)} 个")
except Exception as e:
    log(f"  ✗ 列表获取失败: {e}")
    files = ["config.json", "generation_config.json", "merges.txt", "vocab.json",
             "tokenizer.json", "tokenizer_config.json", "model.safetensors"]

okc = badc = 0
for fn in files:
    if fn.endswith((".md", ".gitattributes")):
        continue
    out = os.path.join(DEST, fn)
    if download(f"{HF}/Qwen/Qwen3-0.6B/resolve/main/{fn}", out, min_size=10):
        okc += 1
    else:
        badc += 1
log(f"  模型下载完成: 成功 {okc} / 失败 {badc}")

log("=" * 70)
log("预取结果清单：")
for d in (DATA, DEST):
    for f in sorted(os.listdir(d)):
        p = os.path.join(d, f)
        if os.path.isfile(p):
            log(f"   {p}  {os.path.getsize(p)/1e6:.2f} MB")
