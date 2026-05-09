from __future__ import annotations

from inboxanchor.infra.text_normalizer import normalize_email_body_text


def test_normalize_email_body_text_extracts_readable_text_from_json_payload():
    payload = (
        '{"body":{"text":"Hello Luca,\\n\\nThe contract is attached and needs a reply this week."},'
        '"metadata":{"source":"gmail"}}'
    )

    normalized = normalize_email_body_text(payload)

    assert "Hello Luca" in normalized
    assert "needs a reply this week" in normalized
    assert "metadata" not in normalized.lower()


def test_normalize_email_body_text_flattens_html_payload():
    payload = '{"html":"<p>Status update</p><p>Your invoice is ready.</p>"}'

    normalized = normalize_email_body_text(payload)

    assert "Status update" in normalized
    assert "Your invoice is ready." in normalized
