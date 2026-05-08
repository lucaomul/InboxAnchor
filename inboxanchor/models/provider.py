from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProviderProfile(BaseModel):
    slug: str
    label: str
    family: str
    auth_mode: str
    status: str
    live_ready: bool = False
    supports_batching: bool = True
    supports_labels: bool = True
    supports_archive: bool = True
    supports_trash: bool = True
    best_for: str
    capabilities: list[str] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)


class ProviderConnectionState(BaseModel):
    provider: str
    status: str = "not_connected"
    account_hint: str = ""
    sync_enabled: bool = False
    dry_run_only: bool = True
    last_tested_at: Optional[datetime] = None
    notes: str = ""
