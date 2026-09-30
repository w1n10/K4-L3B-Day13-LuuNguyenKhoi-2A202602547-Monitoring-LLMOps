from __future__ import annotations

import json
from pathlib import Path

from scripts import build_dashboard

REPO_ROOT = Path(__file__).resolve().parents[1]


def _record(event: str, ts: str, **fields) -> dict:
    return {"ts": ts, "level": "info", "service": "api", "event": event, "correlation_id": "req-00000000", **fields}


def test_dashboard_has_six_panels_and_matches_log_aggregates(tmp_path: Path) -> None:
    ok = dict(latency_ms=100, ttft_ms=50, tokens_in=40, tokens_out=100, cost_usd=0.002, quality_score=0.8, tool_success=True)
    records = [
        _record("request_received", "2026-09-30T02:00:10Z"),
        _record("response_sent", "2026-09-30T02:00:11Z", **ok),
        _record("request_received", "2026-09-30T02:01:10Z"),
        _record("response_sent", "2026-09-30T02:01:13Z", **{**ok, "latency_ms": 2700}),
        _record("request_received", "2026-09-30T02:01:20Z"),
        _record("request_failed", "2026-09-30T02:01:20Z", error_type="RuntimeError", tool_success=False),
    ]
    logs = tmp_path / "logs.jsonl"
    logs.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    out = build_dashboard.build(logs, REPO_ROOT / "config" / "dashboard.yaml", tmp_path / "dash.html")
    page = out.read_text(encoding="utf-8")

    assert page.count('class="panel"') == 6
    assert "last 60 min" in page
    assert "33.3%" in page  # error rate: 1 failed / 3 received
    assert "66.7%" in page  # retrieval success: 2 true / 3 tool results
    assert "$0.0040" in page  # total cost
    assert "RuntimeError: 1" in page
