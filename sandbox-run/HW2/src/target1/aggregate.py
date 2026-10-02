#!/usr/bin/env python3
"""
汇总 HW2 任务一多轮实验结果，生成对照表（Markdown + JSON）。

用法：
  python3 aggregate.py
输出：
  /workspace/HW2/results/target1/summary.md
  /workspace/HW2/results/target1/summary.json
"""

import json
import statistics
from pathlib import Path

BASE = Path("/workspace/HW2/results/target1")
GROUPS = ["shared_prefix", "dispersed_prefix"]
RUNS = ["run-1", "run-2", "run-3"]

METRICS = [
    ("success_rate", "成功率", "{:.2%}"),
    ("cache_hit_rate", "缓存命中率", "{:.2%}"),
    ("total_actual_prefill_tokens", "实际 Prefill token 数", "{:,.0f}"),
    ("avg_actual_prefill_tokens_per_request", "单请求平均 Prefill token", "{:,.1f}"),
    ("output_token_throughput_tps", "输出吞吐 (token/s)", "{:.3f}"),
    ("request_throughput_rps", "请求吞吐 (req/s)", "{:.3f}"),
    ("ttft_p50_s", "TTFT p50 (s)", "{:.3f}"),
    ("ttft_p95_s", "TTFT p95 (s)", "{:.3f}"),
    ("tpot_p50_s", "TPOT p50 (s)", "{:.3f}"),
    ("tpot_p95_s", "TPOT p95 (s)", "{:.3f}"),
    ("e2e_p50_s", "端到端延迟 p50 (s)", "{:.3f}"),
    ("e2e_p95_s", "端到端延迟 p95 (s)", "{:.3f}"),
    ("wall_clock_s", "墙钟时间 (s)", "{:.2f}"),
]


def load(run_dir):
    with open(run_dir / "summary.json") as f:
        return json.load(f)


def main():
    data = {g: {r: load(BASE / g / r) for r in RUNS} for g in GROUPS}

    lines = []
    lines.append("# HW2 任务一：前缀缓存对照实验结果汇总\n")
    lines.append("每组 32 条请求，最大并发 8；temperature=0、max_new_tokens=16、"
                 "ignore_eos=true、sampling_seed=2026；原生 /generate 接口提交 input_ids，流式响应。\n")
    lines.append("输入长度 1024 tokens（共享前缀长度 896 + 各自后缀 128），两组输入/输出长度、"
                 "请求顺序、并发数完全一致。\n")

    # 三轮均值主表
    lines.append("\n## 主表（三轮 run-1/2/3 的平均值）\n")
    lines.append("| 指标 | 共享前缀组 | 分散前缀组 | 差异（共享 vs 分散） |")
    lines.append("| --- | --- | --- | --- |")
    summary_json = {"per_run": data, "mean": {}}
    for key, label, fmt in METRICS:
        vals = {}
        for g in GROUPS:
            vs = [data[g][r][key] for r in RUNS if data[g][r].get(key) is not None]
            vals[g] = statistics.mean(vs) if vs else None
        summary_json["mean"][key] = {g: vals[g] for g in GROUPS}
        a, b = vals["shared_prefix"], vals["dispersed_prefix"]
        if a is None or b is None:
            diff = "-"
        else:
            diff = f"{a - b:+.3f}" if abs(b) > 1e-9 else "-"
        lines.append(f"| {label} | {fmt.format(a)} | {fmt.format(b)} | {diff} |")

    # 逐轮明细
    lines.append("\n## 逐轮明细\n")
    lines.append("| 指标 | " + " | ".join(f"{g} {r}" for g in GROUPS for r in RUNS) + " |")
    lines.append("| --- | " + " | ".join(["---"] * len(GROUPS) * len(RUNS)) + " |")
    for key, label, fmt in METRICS:
        row = [fmt.format(data[g][r][key]) if data[g][r].get(key) is not None else "-"
               for g in GROUPS for r in RUNS]
        lines.append(f"| {label} | " + " | ".join(row) + " |")

    # 关键结论数据
    m = summary_json["mean"]
    hit_s, hit_d = m["cache_hit_rate"]["shared_prefix"], m["cache_hit_rate"]["dispersed_prefix"]
    pf_s, pf_d = m["total_actual_prefill_tokens"]["shared_prefix"], m["total_actual_prefill_tokens"]["dispersed_prefix"]
    ttft_s, ttft_d = m["ttft_p50_s"]["shared_prefix"], m["ttft_p50_s"]["dispersed_prefix"]
    tpot_s, tpot_d = m["tpot_p50_s"]["shared_prefix"], m["tpot_p50_s"]["dispersed_prefix"]
    lines.append("\n## 关键比值\n")
    lines.append(f"- 缓存命中率：共享组 {hit_s:.2%} vs 分散组 {hit_d:.2%}")
    lines.append(f"- 实际 Prefill token 数：{pf_s:,.0f} vs {pf_d:,.0f}"
                 f"（共享组为分散组的 {pf_s / pf_d:.2%}，减少 {(1 - pf_s / pf_d) * 100:.1f}%）")
    lines.append(f"- TTFT p50：{ttft_s:.3f}s vs {ttft_d:.3f}s（降低 {(1 - ttft_s / ttft_d) * 100:.1f}%）")
    lines.append(f"- TPOT p50：{tpot_s:.3f}s vs {tpot_d:.3f}s（变化 {(tpot_s / tpot_d - 1) * 100:+.1f}%）")

    out_md = BASE / "summary.md"
    out_md.write_text("\n".join(lines) + "\n")
    (BASE / "summary.json").write_text(json.dumps(summary_json, indent=2, ensure_ascii=False))
    print("\n".join(lines))
    print(f"\nwritten: {out_md}")


if __name__ == "__main__":
    main()
