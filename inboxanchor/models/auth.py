from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AccountUser(BaseModel):
    id: int
    email: str
    full_name: str
    plan: str = "founder"
    is_active: bool = True
    created_at: datetime
    last_login_at: Optional[datetime] = None


class AuthSession(BaseModel):
    token: str
    user: AccountUser
    created_at: datetime
    expires_at: datetime
