# -*- coding: utf-8 -*-
"""Build report.html for HW3 target1+target3 from run artifacts.

All numbers are read directly from summary.json / requests.csv so the report
cannot drift from the raw results.
"""
import json
import os
import statistics

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "remote")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "report", "report.html")

RUNS = [
    ("A", "A_default", "results/A_default/run-1", "p2c", 5),
    ("B1", "B_cand1", "results/B_candidates/candidate-1/run-1", "p2c", 16),
    ("B2", "B_cand2", "results/B_candidates/candidate-2/run-1", "p2c", 64),
    ("C", "C_affinity", "results/C_affinity/run-1", "consistent-hash", 64),
    ("D", "D_improved", "results/D_improved/run-1", "affinity+负载感知", 64),
]


def load(rel):
    with open(os.path.join(BASE, rel, "summary.json"), encoding="utf-8") as f:
        return json.load(f)


def csv_rows(rel):
    import csv
    with open(os.path.join(BASE, rel, "requests.csv"), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fmt(x, nd=2):
    return f"{x:,.{nd}f}"


def pctl(vals, q):
    vals = sorted(vals)
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def main():
    data = []
    for tag, name, rel, router, mo in RUNS:
        s = load(rel)
        rows = csv_rows(rel)
        ok = [r for r in rows if r["status_code"] == "200"]
        backend = {i: 0 for i in range(4)}
        for r in ok:
            backend[int(r["backend"])] += 1
        data.append(dict(tag=tag, name=name, rel=rel, router=router, mo=mo, s=s,
                         backend=backend))

    # ---------------- main table ----------------
    main_rows = []
    for d in data:
        s = d["s"]
        dist = "/".join(str(d["backend"][i]) for i in range(4))
        main_rows.append(
            "<tr><td>{tag}</td><td>{router}</td><td>{mo}</td>"
            "<td>{sr}</td><td class='num'>{thr}</td><td class='num'>{hit}</td>"
            "<td class='num'>{pf}</td><td class='num'>{tp95}</td>"
            "<td class='num'>{lp95}</td><td class='num'>{dist}</td></tr>".format(
                tag=d["tag"], router=d["router"], mo=d["mo"],
                sr="100%", thr=fmt(s["throughput_rps"]),
                hit=fmt(100 * s["cache_hit_rate"], 1) + "%",
                pf=fmt(s["computed_prefill_tokens_total"] / 1000, 0) + "k",
                tp95=fmt(s["ttft_s"]["p95"]), lp95=fmt(s["latency_s"]["p95"]),
                dist=dist))
    main_table = "\n".join(main_rows)

    # ---------------- phase table (cache hit / ttft p50) ----------------
    phases = ["steady", "burst", "recovery"]
    tiers = ["cold", "warm", "hot", "superhot"]

    def agg(rel, keycol, keys):
        out = {}
        by = {k: dict(n=0, ttft=[], cached=0, prompt=0, lat=[]) for k in keys}
        for r in csv_rows(rel):
            if r["status_code"] != "200":
                continue
            d = by[r[keycol]]
            d["n"] += 1
            d["ttft"].append(float(r["ttft_s"]))
            d["lat"].append(float(r["latency_s"]))
            d["cached"] += int(r["cached_tokens"])
            d["prompt"] += int(r["prompt_tokens"])
        for k, d in by.items():
            out[k] = dict(
                n=d["n"],
                hit=100 * d["cached"] / d["prompt"] if d["prompt"] else 0,
                ttft=statistics.median(d["ttft"]) if d["ttft"] else 0,
                lat=statistics.median(d["lat"]) if d["lat"] else 0)
        return out

    ph_data = {d["tag"]: agg(d["rel"], "traffic_phase", phases) for d in data}
    ti_data = {d["tag"]: agg(d["rel"], "popularity_tier", tiers) for d in data}

    def phase_table(sel):
        head = ("<tr><th>阶段</th>" +
                "".join(f"<th>{t} 命中率 / TTFT p50</th>" for t in sel) + "</tr>")
        lines = [head]
        for p in phases:
            cells = []
            for t in sel:
                v = ph_data[t][p]
                cells.append(f"<td class='num'>{v['hit']:.1f}% / {v['ttft']:.2f}s</td>")
            lines.append(f"<tr><td>{p} (n={ph_data[sel[0]][p]['n']})</td>" +
                         "".join(cells) + "</tr>")
        return "\n".join(lines)

    def tier_table(sel):
        lines = ["<tr><th>热度层</th>" +
                 "".join(f"<th>{t} 命中率 / TTFT p50</th>" for t in sel) + "</tr>"]
        for tier in tiers:
            cells = []
            for t in sel:
                v = ti_data[t][tier]
                cells.append(f"<td class='num'>{v['hit']:.1f}% / {v['ttft']:.2f}s</td>")
            lines.append(f"<tr><td>{tier} (n={ti_data[sel[0]][tier]['n']})</td>" +
                         "".join(cells) + "</tr>")
        return "\n".join(lines)

    # ---------------- target1 table ----------------
    t1 = {}
    for g in ("shared_prefix", "dispersed_prefix"):
        with open(os.path.join(BASE, f"results/target1/{g}/run-1/summary.json"),
                  encoding="utf-8") as f:
            t1[g] = json.load(f)
    a, b = t1["shared_prefix"], t1["dispersed_prefix"]

    def t1_row(label, g):
        return ("<tr><td>{}</td><td>{}/{}</td><td class='num'>{}</td>"
                "<td class='num'>{}</td><td class='num'>{}</td>"
                "<td class='num'>{}</td><td class='num'>{}</td></tr>".format(
                    label, g["successful"], g["requests"], fmt(g["throughput_rps"]),
                    fmt(100 * g["cache_hit_rate"], 2) + "%",
                    f"{g['computed_prefill_tokens_total']:,}",
                    f"{g['ttft_s']['p50']*1000:.1f} / {g['ttft_s']['p95']*1000:.1f}",
                    f"{g['latency_s']['p50']*1000:.0f} / {g['latency_s']['p95']*1000:.0f}"))

    # ---------------- D router fallback stats ----------------
    fb_n = 0
    fb_sessions = set()
    with open(os.path.join(BASE, "results/D_improved/run-1/router_fallbacks.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            fb_n += 1
            fb_sessions.add(json.loads(line)["session_id"])

    # ---------------- charts: backend distribution + throughput/hit --------
    def chart_dist():
        colors = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759"]
        W, H, x0, y0, bw, gap = 640, 150, 60, 20, 46, 62
        parts = [f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg'>"]
        for i, d in enumerate(data):
            total = sum(d["backend"].values())
            x = x0 + i * (bw + gap)
            acc = 0.0
            for bi in range(4):
                frac = d["backend"][bi] / total
                hgt = frac * 110
                y = y0 + 110 - acc - hgt
                parts.append(
                    f"<rect x='{x}' y='{y:.1f}' width='{bw}' height='{hgt:.1f}' "
                    f"fill='{colors[bi]}'/>")
                if frac > 0.09:
                    parts.append(
                        f"<text x='{x+bw/2}' y='{y+hgt/2+3:.1f}' font-size='9' "
                        f"text-anchor='middle' fill='#fff'>{frac*100:.0f}%</text>")
                acc += hgt
            parts.append(f"<text x='{x+bw/2}' y='{y0+124}' font-size='11' "
                         f"text-anchor='middle'>{d['tag']}</text>")
        parts.append(f"<text x='{x0}' y='{y0-6}' font-size='9'>"
                     f"每个后端收到的测量请求占比（0/1/2/3 自下而上）</text>")
        parts.append("</svg>")
        return "".join(parts)

    def chart_thr():
        W, H = 640, 150
        parts = [f"<svg viewBox='0 0 {W} {H}' xmlns='http://www.w3.org/2000/svg'>"]
        maxrps = max(d["s"]["throughput_rps"] for d in data)
        for i, d in enumerate(data):
            x = 60 + i * 108
            h = d["s"]["throughput_rps"] / maxrps * 90
            parts.append(f"<rect x='{x}' y='{110-h:.1f}' width='34' height='{h:.1f}' "
                         f"fill='#4e79a7'/>")
            parts.append(f"<text x='{x+17}' y='{104-h:.1f}' font-size='9' "
                         f"text-anchor='middle'>{d['s']['throughput_rps']:.1f}</text>")
            h2 = d["s"]["cache_hit_rate"] * 90
            parts.append(f"<rect x='{x+42}' y='{110-h2:.1f}' width='34' "
                         f"height='{h2:.1f}' fill='#e15759'/>")
            parts.append(f"<text x='{x+59}' y='{104-h2:.1f}' font-size='9' "
                         f"text-anchor='middle'>{100*d['s']['cache_hit_rate']:.0f}%</text>")
            parts.append(f"<text x='{x+38}' y='{124}' font-size='11' "
                         f"text-anchor='middle'>{d['tag']}</text>")
        parts.append("<text x='60' y='14' font-size='9'>蓝=吞吐 (req/s)，红=缓存命中率"
                     "</text></svg>")
        return "".join(parts)

    # client_queue / dispatch_lag check
    cq = " / ".join(
        f"{d['tag']} {d['s']['client_queue_s']['p95']*1000:.1f}ms" for d in data)
    dl = " / ".join(f"{d['s']['dispatch_lag_s']['p95']*1000:.1f}ms" for d in data)

    ctx = dict(
        main_table=main_table,
        phase_table_abd=phase_table(["A", "B2", "D"]),
        phase_table_c=phase_table(["B2", "C", "D"]),
        tier_table=tier_table(["B2", "C", "D"]),
        t1_shared=t1_row("共享前缀（2048 共享 + 64 独立）", a),
        t1_dispersed=t1_row("分散前缀（2112 全不同）", b),
        t1_hit_s=fmt(100 * a["cache_hit_rate"], 2),
        t1_hit_d=fmt(100 * b["cache_hit_rate"], 2),
        t1_pf_s=f"{a['computed_prefill_tokens_total']:,}",
        t1_pf_d=f"{b['computed_prefill_tokens_total']:,}",
        t1_ttft_ratio=fmt(100 * (1 - a["ttft_s"]["p50"] / b["ttft_s"]["p50"]), 0),
        t1_tpot_s=fmt(a["tpot_s"]["p50"] * 1000, 1),
        t1_tpot_d=fmt(b["tpot_s"]["p50"] * 1000, 1),
        chart_dist=chart_dist(),
        chart_thr=chart_thr(),
        cq=cq, dl=dl,
        fb_n=f"{fb_n:,}", fb_sessions=len(fb_sessions),
        c_share=fmt(100 * data[3]["backend"][3] / 2048, 1),
        # "hottest" = the busiest backend (max request count), same denominator
        # as the 4.1 main table, so the two sections cannot drift apart.
        hot_c=fmt(100 * max(data[3]["backend"].values()) / 2048, 1),
        hot_d=fmt(100 * max(data[4]["backend"].values()) / 2048, 1),
        hit_c=fmt(100 * data[3]["s"]["cache_hit_rate"], 1),
        hit_b2=fmt(100 * data[2]["s"]["cache_hit_rate"], 1),
        hit_d=fmt(100 * data[4]["s"]["cache_hit_rate"], 1),
        thr_c=fmt(data[3]["s"]["throughput_rps"]),
        thr_b2=fmt(data[2]["s"]["throughput_rps"]),
        thr_d=fmt(data[4]["s"]["throughput_rps"]),
        pf_c=fmt(data[3]["s"]["computed_prefill_tokens_total"] / 1000, 0),
        pf_b2=fmt(data[2]["s"]["computed_prefill_tokens_total"] / 1000, 0),
        pf_d=fmt(data[4]["s"]["computed_prefill_tokens_total"] / 1000, 0),
    )

    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "report", "template.html"), encoding="utf-8") as f:
        tpl = f.read()
    for k, v in ctx.items():
        tpl = tpl.replace("@@%s@@" % k, str(v))
    html = tpl
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("written", OUT, len(html), "bytes")


if __name__ == "__main__":
    main()
