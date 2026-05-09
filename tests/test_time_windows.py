from datetime import datetime, timezone

from inboxanchor.core.time_windows import (
    gmail_query_with_time_range,
    imap_since_before_for_time_range,
    in_time_window,
    normalize_time_range,
    resolve_time_window,
)


def test_resolve_time_window_last_month_has_start_and_end():
    window = resolve_time_window("last_month")

    assert window.start_at is not None
    assert window.end_at is not None
    assert window.start_at < window.end_at


def test_normalize_time_range_defaults_to_all_time():
    assert normalize_time_range(None) == "all_time"
    assert normalize_time_range("") == "all_time"


def test_gmail_query_with_time_range_adds_date_operators():
    query = gmail_query_with_time_range("is:unread", "last_3_months")

    assert "is:unread" in query
    assert "after:" in query


def test_imap_time_range_for_older_than_ten_years_only_sets_before():
    since, before = imap_since_before_for_time_range("older_than_10_years")

    assert since is None
    assert before is not None


def test_in_time_window_respects_older_than_ten_years():
    ancient = datetime(2010, 1, 1, tzinfo=timezone.utc)
    recent = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert in_time_window(ancient, "older_than_10_years") is True
    assert in_time_window(recent, "older_than_10_years") is False
