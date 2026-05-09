from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    class StrEnum(str, Enum):
        pass

from pydantic import BaseModel, ConfigDict


class EmailAliasStatus(StrEnum):
    active = "active"
    revoked = "revoked"


class EmailAlias(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: Optional[int] = None
    owner_email: str
    provider: str
    alias_address: str
    target_email: str
    alias_type: str = "plus"
    label: str = ""
    purpose: str = ""
    note: str = ""
    status: EmailAliasStatus = EmailAliasStatus.active
    created_at: datetime
    revoked_at: Optional[datetime] = None
