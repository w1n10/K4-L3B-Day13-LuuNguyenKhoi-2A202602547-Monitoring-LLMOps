from __future__ import annotations

import hashlib
import re

# Thứ tự quan trọng: pattern dài/cụ thể (thẻ, CCCD) chạy trước pattern ngắn (điện thoại)
# để một chuỗi số dài không bị che dở dang bởi pattern ngắn hơn.
PII_PATTERNS: dict[str, str] = {
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    # Thẻ thanh toán: 4 nhóm 4 số cùng một kiểu phân tách, hoặc 13–19 số liền nhau.
    # Không cho phân tách tùy ý giữa từng chữ số để không nuốt số điện thoại đứng cạnh.
    "credit_card": r"(?<!\d)(?:\d{4}([ -]?)\d{4}\1\d{4}\1\d{4}|\d{13,19})(?!\d)",
    "cccd": r"\b\d{12}\b",
    "phone_vn": r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)",
    # Hộ chiếu Việt Nam: 1 chữ cái in hoa + 7 chữ số, ví dụ B1234567.
    "passport": r"\b[A-Z]\d{7}\b",
}

_COMPILED_PATTERNS = {name: re.compile(pattern) for name, pattern in PII_PATTERNS.items()}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in _COMPILED_PATTERNS.items():
        safe = pattern.sub(f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
