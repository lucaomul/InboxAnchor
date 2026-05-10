from __future__ import annotations

import os
import secrets
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from inboxanchor.config.settings import SETTINGS
from inboxanchor.connectors.gmail_transport import (
    GMAIL_MODIFY_SCOPE,
    GMAIL_SEND_SCOPE,
    GMAIL_SETTINGS_BASIC_SCOPE,
)
from inboxanchor.connectors.oauth_flow import build_authorization_url, exchange_code_for_token
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.infra.request_context import get_current_actor_email

router = APIRouter(prefix="/oauth", tags=["oauth"])
GMAIL_PKCE_REGISTRY: dict[str, dict[str, str] | str] = {}
GMAIL_AUTH_SCOPES = [GMAIL_MODIFY_SCOPE, GMAIL_SEND_SCOPE, GMAIL_SETTINGS_BASIC_SCOPE]


def _resolve_token_path() -> str:
    if SETTINGS.gmail_token_path:
        return SETTINGS.gmail_token_path
    if SETTINGS.gmail_credentials_path:
        credentials_path = Path(SETTINGS.gmail_credentials_path).expanduser()
        return str(credentials_path.with_name("token.json"))
    return ""


def _token_data_dir() -> Path:
    return Path(
        os.getenv(
            "INBOXANCHOR_DATA_DIR",
            str(Path(tempfile.gettempdir()) / "inboxanchor"),
        )
    ).expanduser()


def _safe_email_slug(email: str) -> str:
    return (
        email.strip()
        .lower()
        .replace("@", "__at__")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )


def _resolve_token_path_for_owner(owner_email: Optional[str]) -> str:
    normalized_owner = (owner_email or "").strip().lower()
    if normalized_owner:
        token_dir = _token_data_dir() / "oauth" / _safe_email_slug(normalized_owner)
        token_dir.mkdir(parents=True, exist_ok=True)
        token_path = token_dir / "gmail_token.json"
        if token_path.exists():
            return str(token_path)
        legacy_path = _resolve_token_path()
        if legacy_path and Path(legacy_path).expanduser().exists():
            return legacy_path
        return str(token_path)
    return _resolve_token_path()


def _html_page(message: str, *, success: bool) -> HTMLResponse:
    background = "#ffffff" if success else "#111111"
    text = "#111111" if success else "#ffffff"
    body = (
        "<html><body style=\"font-family: sans-serif; padding: 2rem; "
        f"background: {background}; color: {text};\">"
        f"<h2>{escape(message)}</h2>"
        "</body></html>"
    )
    return HTMLResponse(content=body, status_code=200 if success else 400)


def _normalize_auth_url_result(result) -> tuple[str, str, Optional[str]]:
    if isinstance(result, tuple):
        if len(result) == 3:
            return result[0], result[1], result[2]
        if len(result) == 2:
            return result[0], result[1], None
    raise ValueError("Unexpected authorization URL result payload.")


@router.get("/gmail/start")
def gmail_oauth_start():
    if not SETTINGS.gmail_credentials_path:
        return JSONResponse(
            status_code=400,
            content={
                "error": True,
                "message": "GMAIL_CREDENTIALS_PATH is not configured.",
            },
        )

    credentials_path = Path(SETTINGS.gmail_credentials_path).expanduser()
    if not credentials_path.exists():
        return JSONResponse(
            status_code=400,
            content={
                "error": True,
                "message": "Gmail OAuth credentials file was not found.",
            },
        )

    try:
        owner_email = get_current_actor_email()
        auth_url, state, code_verifier = _normalize_auth_url_result(
            build_authorization_url(
                str(credentials_path),
                GMAIL_AUTH_SCOPES,
                redirect_uri=SETTINGS.gmail_redirect_uri,
                state=secrets.token_urlsafe(24),
            )
        )
        if code_verifier:
            GMAIL_PKCE_REGISTRY[state] = {
                "code_verifier": code_verifier,
                "owner_email": owner_email or "",
            }
    except Exception as error:
        return JSONResponse(
            status_code=400,
            content={"error": True, "message": str(error)},
        )

    return {"auth_url": auth_url, "state": state}


@router.get("/gmail/callback")
def gmail_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    if error:
        return _html_page(f"Gmail OAuth failed: {error}", success=False)
    if not code:
        return _html_page("Missing Gmail OAuth code.", success=False)
    if not SETTINGS.gmail_credentials_path:
        return _html_page("GMAIL_CREDENTIALS_PATH is not configured.", success=False)

    owner_email: Optional[str] = get_current_actor_email()
    token_path = _resolve_token_path()
    if not token_path:
        return _html_page("Unable to determine where token.json should be stored.", success=False)

    try:
        pending = GMAIL_PKCE_REGISTRY.pop(state, None) if state else None
        code_verifier: Optional[str]
        if isinstance(pending, dict):
            code_verifier = pending.get("code_verifier")
            owner_email = owner_email or pending.get("owner_email") or None
        else:
            code_verifier = pending
        token_path = _resolve_token_path_for_owner(owner_email)
        exchange_code_for_token(
            SETTINGS.gmail_credentials_path,
            token_path,
            GMAIL_AUTH_SCOPES,
            code=code,
            redirect_uri=SETTINGS.gmail_redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )
        with session_scope() as session:
            repository = InboxRepository(session)
            current = repository.get_provider_connection("gmail", owner_email=owner_email)
            updated = current.model_copy(
                update={
                    "status": "connected",
                    "sync_enabled": True,
                    "dry_run_only": False,
                    "notes": "OAuth token stored locally.",
                    "last_tested_at": datetime.now(timezone.utc),
                }
            )
            repository.save_provider_connection(updated, owner_email=owner_email)
    except Exception as oauth_error:
        return _html_page(f"Gmail OAuth failed: {oauth_error}", success=False)

    return _html_page("Gmail connected successfully. You can close this window.", success=True)
