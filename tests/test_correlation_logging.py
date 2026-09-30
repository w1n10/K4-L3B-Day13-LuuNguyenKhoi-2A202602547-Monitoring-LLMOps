from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx

from app import logging_config
from app.main import app

RAW_PII = ("student@vinuni.edu.vn", "0987654321", "4111 1111 1111 1111", "001099012345")


def _post(messages: list[tuple[dict, dict]]) -> list[httpx.Response]:
    async def send_all() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return [
                await client.post("/chat", json=body, headers=headers)
                for body, headers in messages
            ]

    return asyncio.run(send_all())


def _body(user_id: str, message: str) -> dict:
    return {"user_id": user_id, "session_id": f"s-{user_id}", "feature": "qa", "message": message}


def test_correlation_id_generated_echoed_and_not_leaked(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    first, second, custom, unsafe = _post(
        [
            (_body("u1", "What is monitoring?"), {}),
            (_body("u2", "What is policy?"), {}),
            (_body("u3", "Explain refund"), {"x-request-id": "req-abcdef12"}),
            (_body("u4", "Explain refund"), {"x-request-id": "bad id\n{inject}"}),
        ]
    )

    for response in (first, second, unsafe):
        assert re.fullmatch(r"req-[0-9a-f]{8}", response.headers["x-request-id"])
    assert custom.headers["x-request-id"] == "req-abcdef12"
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    assert first.json()["correlation_id"] == first.headers["x-request-id"]
    assert int(first.headers["x-response-time-ms"]) >= 0

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    api_records = [r for r in records if r.get("service") == "api"]
    by_cid: dict[str, set[str]] = {}
    for record in api_records:
        for field in ("user_id_hash", "session_id", "feature", "model", "env"):
            assert record.get(field), (field, record)
        by_cid.setdefault(record["correlation_id"], set()).add(record["session_id"])
    # Mỗi correlation_id chỉ gắn với đúng một session: context không rò giữa request.
    assert len(by_cid) == 4
    assert all(len(sessions) == 1 for sessions in by_cid.values())


def test_pii_is_scrubbed_before_log_file_is_written(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    # Ngắn hơn 80 ký tự sau khi che để preview không bị cắt mất nhãn cuối.
    message = "student@vinuni.edu.vn 0987654321 4111 1111 1111 1111 001099012345"
    (response,) = _post([(_body("u5", message), {})])

    assert response.status_code == 200
    raw = log_path.read_text(encoding="utf-8")
    for value in RAW_PII:
        assert value not in raw
    for label in ("REDACTED_EMAIL", "REDACTED_PHONE_VN", "REDACTED_CREDIT_CARD", "REDACTED_CCCD"):
        assert label in raw
