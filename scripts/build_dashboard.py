"""Dựng dashboard 6 panel từ data/logs.jsonl theo contract config/dashboard.yaml.

Ví dụ:
    python scripts/build_dashboard.py            # tạo data/dashboard.html một lần
    python scripts/build_dashboard.py --watch    # tạo lại mỗi refresh_seconds (trang tự reload)
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

LOCAL_TZ = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")
SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"]
OPERATOR_TEXT = {"lte": "≤", "gte": "≥"}

W, H = 560, 210
PAD_L, PAD_R, PAD_T, PAD_B = 52, 100, 12, 26


# ---------------------------------------------------------------- data


def load_records(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            rec["_ts"] = datetime.fromisoformat(rec["ts"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        records.append(rec)
    return records


@dataclass
class Window:
    start: datetime
    end: datetime
    minutes: list[datetime] = field(default_factory=list)


def make_window(records: list[dict], range_minutes: int) -> Window:
    end = max(r["_ts"] for r in records).replace(second=0, microsecond=0)
    start = end - timedelta(minutes=range_minutes - 1)
    minutes = [start + timedelta(minutes=i) for i in range(range_minutes)]
    return Window(start=start, end=end + timedelta(minutes=1), minutes=minutes)


def by_minute(records: list[dict], event: str) -> dict[datetime, list[dict]]:
    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("event") == event:
            buckets[r["_ts"].replace(second=0, microsecond=0)].append(r)
    return buckets


def pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 2) if whole else None


def passes(value: float | None, threshold: dict) -> bool | None:
    if value is None:
        return None
    return value <= threshold["value"] if threshold["operator"] == "lte" else value >= threshold["value"]


def compute(records: list[dict], window: Window) -> dict:
    in_window = [r for r in records if window.start <= r["_ts"] < window.end]
    sent = [r for r in in_window if r.get("event") == "response_sent"]
    received = [r for r in in_window if r.get("event") == "request_received"]
    failed = [r for r in in_window if r.get("event") == "request_failed"]
    tool = [r for r in in_window if r.get("tool_success") is not None]

    sent_m = by_minute(in_window, "response_sent")
    recv_m = by_minute(in_window, "request_received")
    fail_m = by_minute(in_window, "request_failed")
    tool_m: dict[datetime, list[dict]] = defaultdict(list)
    for r in tool:
        tool_m[r["_ts"].replace(second=0, microsecond=0)].append(r)

    def series(fn, buckets):
        return [fn(buckets[m]) if buckets.get(m) else None for m in window.minutes]

    lat = lambda p: (lambda rs: percentile([r["latency_ms"] for r in rs], p))
    latest_minute = window.minutes[-1]

    return {
        "count": {"received": len(received), "sent": len(sent), "failed": len(failed)},
        "latency": {
            "series": {
                "P50": series(lat(50), sent_m),
                "P95": series(lat(95), sent_m),
                "P99": series(lat(99), sent_m),
                "TTFT P95": series(lambda rs: percentile([r["ttft_ms"] for r in rs], 95), sent_m),
            },
            "agg": {
                "p50": percentile([r["latency_ms"] for r in sent], 50) if sent else None,
                "p95": percentile([r["latency_ms"] for r in sent], 95) if sent else None,
                "p99": percentile([r["latency_ms"] for r in sent], 99) if sent else None,
                "ttft_p95": percentile([r["ttft_ms"] for r in sent], 95) if sent else None,
            },
        },
        "traffic": {
            "series": {"Requests": series(len, recv_m)},
            "agg": {"count": len(received), "rate_per_minute": len(recv_m.get(latest_minute, []))},
        },
        "errors": {
            "series": {
                "Error rate": [
                    pct(len(fail_m.get(m, [])), len(recv_m.get(m, []))) for m in window.minutes
                ],
                "Retrieval success": series(
                    lambda rs: pct(sum(r["tool_success"] is True for r in rs), len(rs)), tool_m
                ),
            },
            "agg": {
                "error_rate_pct": pct(len(failed), len(received)),
                "tool_success_rate_pct": pct(sum(r["tool_success"] is True for r in tool), len(tool)),
                "count_by_value": dict(Counter(r.get("error_type") for r in failed)),
            },
        },
        "cost": {
            "series": {"Cost": series(lambda rs: round(sum(r["cost_usd"] for r in rs), 6), sent_m)},
            "agg": {"total": round(sum(r["cost_usd"] for r in sent), 6)},
        },
        "tokens": {
            "series": {
                "Input": series(lambda rs: sum(r["tokens_in"] for r in rs), sent_m),
                "Output": series(lambda rs: sum(r["tokens_out"] for r in rs), sent_m),
            },
            "agg": {
                "tokens_in": sum(r["tokens_in"] for r in sent),
                "tokens_out": sum(r["tokens_out"] for r in sent),
            },
        },
        "quality": {
            "series": {"Mean quality": series(lambda rs: round(mean(r["quality_score"] for r in rs), 3), sent_m)},
            "agg": {"mean": round(mean(r["quality_score"] for r in sent), 3) if sent else None},
        },
    }


# ---------------------------------------------------------------- rendering


def fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "usd":
        return f"${value:,.4f}"
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "score_0_to_1":
        return f"{value:.2f}"
    if unit == "ms":
        return f"{value:,.0f} ms"
    return f"{value:,.0f}"


def nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        candidate = step * magnitude
        if candidate >= value:
            return candidate
    return value


def y_max_for(values: list[float], extra: float | None, fixed: float | None) -> float:
    if fixed is not None:
        return fixed
    peak = max([v for v in values if v is not None] + ([extra] if extra is not None else []) + [0])
    return nice_max(peak * 1.1) if peak else 1.0


def chart_svg(
    minutes: list[datetime],
    series: dict[str, list[float | None]],
    unit: str,
    kind: str,
    threshold_line: float | None = None,
    y_fixed: float | None = None,
) -> str:
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    n = len(minutes)
    all_values = [v for vals in series.values() for v in vals if v is not None]
    y_max = y_max_for(all_values, threshold_line, y_fixed)
    x = lambda i: PAD_L + (i + 0.5) * plot_w / n
    y = lambda v: PAD_T + plot_h - (v / y_max) * plot_h
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" class="chart">']

    for frac in (0, 0.5, 1):
        gy = PAD_T + plot_h - frac * plot_h
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{gy:.1f}" y2="{gy:.1f}"/>')
        parts.append(f'<text class="tick" x="{PAD_L - 6}" y="{gy + 4:.1f}" text-anchor="end">{html.escape(fmt(y_max * frac, unit))}</text>')
    for i in range(0, n, 15):
        parts.append(f'<text class="tick" x="{x(i):.1f}" y="{H - 8}" text-anchor="middle">{minutes[i].astimezone(LOCAL_TZ):%H:%M}</text>')
    parts.append(f'<text class="tick" x="{x(n - 1):.1f}" y="{H - 8}" text-anchor="middle">{minutes[-1].astimezone(LOCAL_TZ):%H:%M}</text>')

    if threshold_line is not None:
        ty = y(threshold_line)
        parts.append(f'<line class="threshold" x1="{PAD_L}" x2="{W - PAD_R}" y1="{ty:.1f}" y2="{ty:.1f}"/>')
        parts.append(f'<text class="threshold-label" x="{PAD_L + 4}" y="{ty - 4:.1f}">threshold {html.escape(fmt(threshold_line, unit))}</text>')

    names = list(series)
    if kind == "bar":
        group_w = plot_w / n
        bar_w = max(2.0, (group_w - 2) / len(names) - 1)
        for s_idx, name in enumerate(names):
            for i, v in enumerate(series[name]):
                if not v:
                    continue
                bx = PAD_L + i * group_w + 1 + s_idx * (bar_w + 1)
                parts.append(
                    f'<rect x="{bx:.1f}" y="{y(v):.1f}" width="{bar_w:.1f}" height="{max(1.0, y(0) - y(v)):.1f}" '
                    f'rx="1.5" fill="{SERIES[s_idx]}"/>'
                )
    else:
        end_labels = []
        for s_idx, name in enumerate(names):
            vals = series[name]
            segment: list[str] = []
            segments: list[list[str]] = []
            for i, v in enumerate(vals):
                if v is None:
                    if segment:
                        segments.append(segment)
                    segment = []
                    continue
                segment.append(f"{x(i):.1f},{y(v):.1f}")
                parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="3" fill="{SERIES[s_idx]}" class="dot"/>')
            if segment:
                segments.append(segment)
            for seg in segments:
                if len(seg) > 1:
                    parts.append(f'<polyline points="{" ".join(seg)}" fill="none" stroke="{SERIES[s_idx]}" stroke-width="2" stroke-linejoin="round"/>')
            last = next(((i, v) for i, v in reversed(list(enumerate(vals))) if v is not None), None)
            if last:
                end_labels.append([y(last[1]), name, s_idx])
        # Direct label ở mép phải, giãn cách tối thiểu 12px để không chồng nhau.
        end_labels.sort()
        for k in range(1, len(end_labels)):
            end_labels[k][0] = max(end_labels[k][0], end_labels[k - 1][0] + 12)
        # Nếu nhãn cuối tràn xuống dưới trục x thì đẩy cả cụm lên.
        overflow = end_labels[-1][0] - (PAD_T + plot_h - 4) if end_labels else 0
        for label in end_labels:
            label[0] -= max(0, overflow)
        for ly, name, s_idx in end_labels:
            parts.append(f'<text class="direct" x="{W - PAD_R + 6}" y="{ly + 4:.1f}">{html.escape(name)}</text>')

    # Cột hover trong suốt cho tooltip + crosshair.
    for i, minute in enumerate(minutes):
        rows = [f"{name}: {fmt(series[name][i], unit)}" for name in names if series[name][i] is not None]
        if not rows:
            continue
        tip = html.escape(json.dumps({"t": f"{minute.astimezone(LOCAL_TZ):%H:%M}", "rows": rows}))
        parts.append(
            f'<rect class="hit" x="{PAD_L + i * plot_w / n:.1f}" y="{PAD_T}" width="{plot_w / n:.1f}" '
            f'height="{plot_h}" data-x="{x(i):.1f}" data-tip="{tip}"/>'
        )
    parts.append(f'<line class="crosshair" x1="0" x2="0" y1="{PAD_T}" y2="{PAD_T + plot_h}"/>')
    parts.append("</svg>")
    return "".join(parts)


def legend(names: list[str]) -> str:
    if len(names) < 2:
        return ""
    items = "".join(
        f'<span class="key"><i style="background:{SERIES[i]}"></i>{html.escape(n)}</span>' for i, n in enumerate(names)
    )
    return f'<div class="legend">{items}</div>'


def status_badge(ok: bool | None) -> str:
    if ok is None:
        return '<span class="status none">○ no data</span>'
    return '<span class="status good">✓ within threshold</span>' if ok else '<span class="status bad">▲ breach</span>'


def data_table(minutes: list[datetime], series: dict[str, list[float | None]], unit: str) -> str:
    head = "".join(f"<th>{html.escape(n)}</th>" for n in series)
    rows = []
    for i, m in enumerate(minutes):
        if all(series[n][i] is None for n in series):
            continue
        cells = "".join(f"<td>{html.escape(fmt(series[n][i], unit))}</td>" for n in series)
        rows.append(f"<tr><td>{m.astimezone(LOCAL_TZ):%H:%M}</td>{cells}</tr>")
    return (
        f'<details><summary>Data table</summary><table><tr><th>Minute</th>{head}</tr>{"".join(rows)}</table></details>'
    )


def render(contract: dict, data: dict, window: Window, source: Path) -> str:
    dash = contract["dashboard"]
    panels = {p["id"]: p for p in dash["panels"]}
    cards = []

    def stat(label: str, value: str, strong: bool = False) -> str:
        return f'<div class="stat{" strong" if strong else ""}"><span>{html.escape(label)}</span><b>{html.escape(value)}</b></div>'

    for pid in ("latency", "traffic", "errors", "cost", "tokens", "quality"):
        panel, d = panels[pid], data[pid]
        th = panel["threshold"]
        unit = panel["unit"]
        agg_key = th["aggregation"]
        rule = f'{agg_key} {OPERATOR_TEXT[th["operator"]]} {fmt(th["value"], unit)}'

        if pid == "latency":
            a = d["agg"]
            stats = stat("P50", fmt(a["p50"], "ms")) + stat("P95", fmt(a["p95"], "ms"), True) + stat("P99", fmt(a["p99"], "ms")) + stat("TTFT P95", fmt(a["ttft_p95"], "ms"))
            ok = passes(a["p95"], th)
            svg = chart_svg(window.minutes, d["series"], "ms", "line", threshold_line=th["value"])
        elif pid == "traffic":
            a = d["agg"]
            stats = stat("Requests (60 min)", fmt(a["count"], "")) + stat("Latest minute", f'{a["rate_per_minute"]} req/min', True)
            ok = passes(a["rate_per_minute"], th)
            svg = chart_svg(window.minutes, d["series"], "", "bar", threshold_line=th["value"])
        elif pid == "errors":
            a = d["agg"]
            breakdown = ", ".join(f"{k}: {v}" for k, v in a["count_by_value"].items()) or "none"
            stats = (
                stat("Error rate", fmt(a["error_rate_pct"], "percent"), True)
                + stat("Retrieval success", fmt(a["tool_success_rate_pct"], "percent"), True)
                + stat("Errors by type", breakdown)
            )
            ok = passes(a["error_rate_pct"], th)
            svg = chart_svg(window.minutes, d["series"], "percent", "line", threshold_line=th["value"], y_fixed=100)
            rule += " · retrieval success ≥ 90%"
        elif pid == "cost":
            a = d["agg"]
            stats = stat("Total (60 min)", fmt(a["total"], "usd"), True) + stat("Budget", fmt(th["value"], "usd")) + stat("Budget used", f'{a["total"] / th["value"] * 100:.2f}%')
            ok = passes(a["total"], th)
            svg = chart_svg(window.minutes, d["series"], "usd", "bar")
            rule += " (total per window; bars = USD per minute)"
        elif pid == "tokens":
            a = d["agg"]
            stats = stat("Input total", fmt(a["tokens_in"], ""), True) + stat("Output total", fmt(a["tokens_out"], ""), True)
            ok = passes(max(a["tokens_in"], a["tokens_out"]), th)
            svg = chart_svg(window.minutes, d["series"], "", "bar")
            rule += " per field (bars = tokens per minute)"
        else:
            a = d["agg"]
            stats = stat("Mean quality", fmt(a["mean"], unit), True)
            ok = passes(a["mean"], th)
            svg = chart_svg(window.minutes, d["series"], unit, "line", threshold_line=th["value"], y_fixed=1.0)

        cards.append(
            f'<section class="panel" aria-label="{html.escape(panel["title"])}">'
            f'<header><h2>{html.escape(panel["title"])}</h2>{status_badge(ok)}</header>'
            f'<p class="meta">Unit: <code>{html.escape(unit)}</code> · Threshold: <code>{html.escape(rule)}</code></p>'
            f'<div class="stats">{stats}</div>{legend(list(d["series"]))}{svg}'
            f'{data_table(window.minutes, d["series"], "percent" if pid == "errors" else unit)}</section>'
        )

    start_local = window.start.astimezone(LOCAL_TZ)
    end_local = window.end.astimezone(LOCAL_TZ)
    c = data["count"]
    return PAGE.format(
        title=html.escape(dash["title"]),
        refresh=dash["refresh_seconds"],
        range_minutes=dash["time_range_minutes"],
        start=f"{start_local:%Y-%m-%d %H:%M}",
        end=f"{end_local:%H:%M}",
        generated=f"{datetime.now(LOCAL_TZ):%Y-%m-%d %H:%M:%S}",
        source=html.escape(source.as_posix()),
        counts=f'{c["received"]} received · {c["sent"]} sent · {c["failed"]} failed',
        cards="".join(cards),
    )


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>{title}</title>
<style>
:root {{ color-scheme: light; --surface-0:#f4f3f0; --surface-1:#fcfcfb; --border:#e2e1dc; --text-primary:#0b0b0b;
  --text-secondary:#52514e; --text-muted:#7a7974; --grid:#e8e7e3; --series-1:#2a78d6; --series-2:#eb6834;
  --series-3:#1baf7a; --series-4:#eda100; --good:#0ca30c; --critical:#d03b3b; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ color-scheme: dark; --surface-0:#111110;
  --surface-1:#1a1a19; --border:#2e2e2c; --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8f8e86;
  --grid:#2a2a28; --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; --series-4:#c98500; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface-0:#111110; --surface-1:#1a1a19; --border:#2e2e2c;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8f8e86; --grid:#2a2a28; --series-1:#3987e5;
  --series-2:#d95926; --series-3:#199e70; --series-4:#c98500; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--surface-0); color:var(--text-primary); font:14px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif; }}
.top {{ padding:16px 20px 4px; display:flex; flex-wrap:wrap; gap:8px 20px; align-items:baseline; }}
h1 {{ font-size:18px; margin:0; }}
.top p {{ margin:0; color:var(--text-secondary); }}
.range {{ font-weight:600; color:var(--text-primary); }}
.grid-panels {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr)); gap:14px; padding:14px 20px 24px; }}
.panel {{ background:var(--surface-1); border:1px solid var(--border); border-radius:10px; padding:14px 14px 8px; min-width:0; }}
.panel header {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
h2 {{ font-size:15px; margin:0; }}
.meta {{ margin:4px 0 8px; color:var(--text-muted); font-size:12px; }}
code {{ font-size:12px; color:var(--text-secondary); }}
.stats {{ display:flex; flex-wrap:wrap; gap:6px 18px; margin-bottom:6px; }}
.stat span {{ display:block; font-size:11px; color:var(--text-muted); }}
.stat b {{ font-weight:500; font-variant-numeric:tabular-nums; }}
.stat.strong b {{ font-size:18px; font-weight:650; }}
.status {{ font-size:12px; font-weight:600; white-space:nowrap; }}
.status.good {{ color:var(--good); }} .status.bad {{ color:var(--critical); }} .status.none {{ color:var(--text-muted); }}
.legend {{ display:flex; gap:14px; font-size:12px; color:var(--text-secondary); }}
.key i {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }}
.chart {{ width:100%; height:auto; display:block; }}
.grid {{ stroke:var(--grid); stroke-width:1; }}
.tick {{ fill:var(--text-muted); font-size:10px; font-variant-numeric:tabular-nums; }}
.direct {{ fill:var(--text-secondary); font-size:10px; }}
.threshold {{ stroke:var(--critical); stroke-width:1.5; stroke-dasharray:5 4; }}
.threshold-label {{ fill:var(--text-secondary); font-size:10px; }}
.dot {{ stroke:var(--surface-1); stroke-width:1.5; }}
.hit {{ fill:transparent; cursor:crosshair; }}
.crosshair {{ stroke:var(--text-muted); stroke-width:1; visibility:hidden; pointer-events:none; }}
details {{ margin-top:4px; font-size:12px; color:var(--text-secondary); }}
table {{ border-collapse:collapse; margin-top:6px; font-variant-numeric:tabular-nums; }}
td, th {{ padding:2px 10px 2px 0; text-align:right; }} th {{ color:var(--text-muted); font-weight:500; }}
#tip {{ position:fixed; pointer-events:none; background:var(--surface-1); border:1px solid var(--border); border-radius:6px;
  padding:6px 8px; font-size:12px; box-shadow:0 2px 8px rgba(0,0,0,.15); display:none; z-index:10; }}
#tip b {{ display:block; margin-bottom:2px; }}
</style></head>
<body>
<div class="top"><h1>{title}</h1>
<p>Time range: <span class="range">last {range_minutes} min · {start} → {end} (UTC+7)</span></p>
<p>Refresh {refresh}s · generated {generated} · source <code>{source}</code> · {counts}</p></div>
<main class="grid-panels">{cards}</main>
<div id="tip"></div>
<script>
const tip = document.getElementById("tip");
document.querySelectorAll(".hit").forEach((el) => {{
  const cross = el.ownerSVGElement.querySelector(".crosshair");
  el.addEventListener("mousemove", (e) => {{
    const d = JSON.parse(el.dataset.tip);
    tip.innerHTML = "<b>" + d.t + "</b>" + d.rows.join("<br>");
    tip.style.display = "block";
    tip.style.left = Math.min(e.clientX + 12, innerWidth - tip.offsetWidth - 8) + "px";
    tip.style.top = e.clientY + 12 + "px";
    cross.setAttribute("x1", el.dataset.x); cross.setAttribute("x2", el.dataset.x);
    cross.style.visibility = "visible";
  }});
  el.addEventListener("mouseleave", () => {{ tip.style.display = "none"; cross.style.visibility = "hidden"; }});
}});
</script>
</body></html>
"""


def build(log_path: Path, config_path: Path, out_path: Path) -> Path:
    contract = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    records = load_records(log_path)
    if not records:
        raise SystemExit(f"Không có log hợp lệ trong {log_path}; chạy API và load test trước.")
    window = make_window(records, contract["dashboard"]["time_range_minutes"])
    page = render(contract, compute(records, window), window, log_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return out_path


def main() -> None:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ structured log")
    parser.add_argument("--logs", type=Path, default=Path("data/logs.jsonl"))
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config" / "dashboard.yaml")
    parser.add_argument("--out", type=Path, default=Path("data/dashboard.html"))
    parser.add_argument("--watch", action="store_true", help="Tạo lại theo refresh_seconds của contract")
    args = parser.parse_args()

    refresh = yaml.safe_load(args.config.read_text(encoding="utf-8"))["dashboard"]["refresh_seconds"]
    while True:
        out = build(args.logs, args.config, args.out)
        print(f"Dashboard: {out.resolve()}")
        if not args.watch:
            break
        time.sleep(refresh)


if __name__ == "__main__":
    main()
