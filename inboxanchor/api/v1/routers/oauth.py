from __future__ import annotations

import secrets
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from inboxanchor.config.settings import SETTINGS
from inboxanchor.connectors.gmail_transport import GMAIL_MODIFY_SCOPE
from inboxanchor.connectors.oauth_flow import build_authorization_url, exchange_code_for_token
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _resolve_token_path() -> str:
    if SETTINGS.gmail_token_path:
        return SETTINGS.gmail_token_path
    if SETTINGS.gmail_credentials_path:
        credentials_path = Path(SETTINGS.gmail_credentials_path).expanduser()
        return str(credentials_path.with_name("token.json"))
    return ""


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
        auth_url, state = build_authorization_url(
            str(credentials_path),
            [GMAIL_MODIFY_SCOPE],
            redirect_uri=SETTINGS.gmail_redirect_uri,
            state=secrets.token_urlsafe(24),
        )
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

    token_path = _resolve_token_path()
    if not token_path:
        return _html_page("Unable to determine where token.json should be stored.", success=False)

    try:
        exchange_code_for_token(
            SETTINGS.gmail_credentials_path,
            token_path,
            [GMAIL_MODIFY_SCOPE],
            code=code,
            redirect_uri=SETTINGS.gmail_redirect_uri,
            state=state,
        )
        with session_scope() as session:
            repository = InboxRepository(session)
            current = repository.get_provider_connection("gmail")
            updated = current.model_copy(
                update={
                    "status": "connected",
                    "sync_enabled": True,
                    "dry_run_only": False,
                    "notes": "OAuth token stored locally.",
                    "last_tested_at": datetime.now(timezone.utc),
                }
            )
            repository.save_provider_connection(updated)
    except Exception as oauth_error:
        return _html_page(f"Gmail OAuth failed: {oauth_error}", success=False)

    return _html_page("Gmail connected successfully. You can close this window.", success=True)
