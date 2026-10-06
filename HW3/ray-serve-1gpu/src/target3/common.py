"""Shared helpers for HW3 target3 tooling (analyze.py, serve_app.py support)."""

import math
import statistics


def percentile(values, fraction):
    """Nearest-rank percentile in [0, 1]; None for empty input."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[min(index, len(ordered) - 1)]


def stats(values):
    return {
        "mean": statistics.fmean(values) if values else None,
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def fmt(value, digits=4):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def markdown_table(headers, rows):
    """Render a small markdown table."""
    widths = [len(h) for h in headers]
    str_rows = [[str(cell) for cell in row] for row in rows]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = []
    lines.append("| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |")
    lines.append("| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |")
    for row in str_rows:
        lines.append("| " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) + " |")
    return "\n".join(lines)
