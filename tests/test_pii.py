from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd_card_and_passport() -> None:
    samples = {
        "CCCD 001099012345": "REDACTED_CCCD",
        "card 4111 1111 1111 1111": "REDACTED_CREDIT_CARD",
        "card 4111-1111-1111-1111": "REDACTED_CREDIT_CARD",
        "card 4111111111111111": "REDACTED_CREDIT_CARD",
        "passport B1234567": "REDACTED_PASSPORT",
    }

    for text, label in samples.items():
        out = scrub_text(text)
        assert label in out, out
        assert not any(ch.isdigit() for ch in out.split(" ", 1)[1].replace(label, "")), out


def test_scrub_keeps_normal_text() -> None:
    text = "Explain P95 latency for claude-sonnet-4-5 over 60 minutes"
    assert scrub_text(text) == text


def test_adjacent_phone_and_card_get_their_own_labels() -> None:
    out = scrub_text("0987654321 4111 1111 1111 1111 001099012345")
    assert out == "[REDACTED_PHONE_VN] [REDACTED_CREDIT_CARD] [REDACTED_CCCD]"
