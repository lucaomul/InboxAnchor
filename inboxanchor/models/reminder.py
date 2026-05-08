from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FollowUpReminderStatus(StrEnum):
    active = "active"
    completed = "completed"
    dismissed = "dismissed"


class FollowUpReminder(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: Optional[int] = None
    provider: str
    email_id: str
    owner_email: str = "workspace@inboxanchor.local"
    thread_id: str = ""
    run_id: Optional[str] = None
    sender: str
    subject: str
    preview: str = ""
    priority: str = "medium"
    category: str = "unknown"
    note: str = ""
    source: str = "dashboard"
    due_at: datetime
    status: FollowUpReminderStatus = FollowUpReminderStatus.active
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None
