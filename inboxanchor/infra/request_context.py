from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Optional

_CURRENT_ACTOR_EMAIL: ContextVar[Optional[str]] = ContextVar(
    "inboxanchor_current_actor_email",
    default=None,
)


def get_current_actor_email() -> Optional[str]:
    return _CURRENT_ACTOR_EMAIL.get()


def set_current_actor_email(email: Optional[str]) -> Token:
    return _CURRENT_ACTOR_EMAIL.set(email.strip().lower() if email else None)


def reset_current_actor_email(token: Token) -> None:
    _CURRENT_ACTOR_EMAIL.reset(token)
