from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Optional

ALL_TIME_RANGE = "all_time"
DEFAULT_TIME_RANGE = ALL_TIME_RANGE

TIME_RANGE_LABELS: dict[str, str] = {
    ALL_TIME_RANGE: "All time",
    "today": "Today",
    "last_7_days": "Last 7 days",
    "this_month": "This month",
    "last_month": "Last month",
    "last_3_months": "Last 3 months",
    "last_6_months": "Last 6 months",
    "last_1_year": "Last year",
    "last_3_years": "Last 3 years",
    "last_5_years": "Last 5 years",
    "last_10_years": "Last 10 years",
    "older_than_10_years": "10+ years ago",
}


@dataclass(frozen=True)
class MailboxTimeWindow:
    preset: str
    label: str
    start_at: Optional[datetime]
    end_at: Optional[datetime]

    @property
    def is_unbounded(self) -> bool:
        return self.start_at is None and self.end_at is None


def available_time_ranges() -> list[dict[str, str]]:
    return [
        {"value": value, "label": label}
        for value, label in TIME_RANGE_LABELS.items()
    ]


def normalize_time_range(value: Optional[str]) -> str:
    cleaned = (value or "").strip().lower()
    if not cleaned or cleaned == ALL_TIME_RANGE:
        return ALL_TIME_RANGE
    if cleaned not in TIME_RANGE_LABELS:
        allowed = ", ".join(TIME_RANGE_LABELS)
        raise ValueError(f"Unsupported time range '{value}'. Expected one of: {allowed}.")
    return cleaned


def time_range_label(value: Optional[str]) -> str:
    return TIME_RANGE_LABELS[normalize_time_range(value)]


def resolve_time_window(
    value: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> MailboxTimeWindow:
    preset = normalize_time_range(value)
    label = TIME_RANGE_LABELS[preset]
    reference = _resolve_reference_now(now)
    start_of_today = datetime.combine(
        reference.date(),
        time.min,
        tzinfo=reference.tzinfo,
    )

    if preset == ALL_TIME_RANGE:
        return MailboxTimeWindow(preset=preset, label=label, start_at=None, end_at=None)
    if preset == "today":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=start_of_today.astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "last_7_days":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=(start_of_today - timedelta(days=7)).astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "this_month":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=_month_floor(reference).astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "last_month":
        current_month = _month_floor(reference)
        previous_month = _shift_months(current_month, -1)
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=previous_month.astimezone(timezone.utc),
            end_at=current_month.astimezone(timezone.utc),
        )
    if preset == "last_3_months":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=_shift_months(start_of_today, -3).astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "last_6_months":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=_shift_months(start_of_today, -6).astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "last_1_year":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=_shift_months(start_of_today, -12).astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "last_3_years":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=_shift_months(start_of_today, -36).astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "last_5_years":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=_shift_months(start_of_today, -60).astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "last_10_years":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=_shift_months(start_of_today, -120).astimezone(timezone.utc),
            end_at=None,
        )
    if preset == "older_than_10_years":
        return MailboxTimeWindow(
            preset=preset,
            label=label,
            start_at=None,
            end_at=_shift_months(start_of_today, -120).astimezone(timezone.utc),
        )
    raise AssertionError(f"Unhandled time range preset: {preset}")


def in_time_window(received_at: datetime, value: Optional[str]) -> bool:
    window = resolve_time_window(value)
    if window.start_at and received_at < window.start_at:
        return False
    if window.end_at and received_at >= window.end_at:
        return False
    return True


def gmail_query_with_time_range(base_query: Optional[str], value: Optional[str]) -> Optional[str]:
    window = resolve_time_window(value)
    query_parts = [part for part in [(base_query or "").strip()] if part]
    if window.start_at is not None:
        query_parts.append(f"after:{window.start_at.astimezone(timezone.utc).strftime('%Y/%m/%d')}")
    if window.end_at is not None:
        query_parts.append(f"before:{window.end_at.astimezone(timezone.utc).strftime('%Y/%m/%d')}")
    return " ".join(query_parts) or None


def imap_since_before_for_time_range(value: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    window = resolve_time_window(value)
    since = (
        window.start_at.astimezone(timezone.utc).strftime("%d-%b-%Y")
        if window.start_at is not None
        else None
    )
    before = (
        window.end_at.astimezone(timezone.utc).strftime("%d-%b-%Y")
        if window.end_at is not None
        else None
    )
    return since, before


def _resolve_reference_now(now: Optional[datetime]) -> datetime:
    reference = now or datetime.now().astimezone()
    if reference.tzinfo is None:
        return reference.replace(tzinfo=timezone.utc)
    return reference


def _month_floor(value: datetime) -> datetime:
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _shift_months(value: datetime, months: int) -> datetime:
    total_months = (value.year * 12 + (value.month - 1)) + months
    year = total_months // 12
    month = (total_months % 12) + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
