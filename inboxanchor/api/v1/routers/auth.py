from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from inboxanchor.config.settings import SETTINGS
from inboxanchor.connectors.gmail_transport import GMAIL_MODIFY_SCOPE
from inboxanchor.connectors.oauth_flow import build_authorization_url, exchange_code_for_token
from inboxanchor.infra.auth import AuthError, AuthService
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    full_name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class GmailCodeExchangeRequest(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = None


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _resolve_gmail_token_path() -> str:
    if SETTINGS.gmail_token_path:
        return SETTINGS.gmail_token_path
    if SETTINGS.gmail_credentials_path:
        credentials_path = Path(SETTINGS.gmail_credentials_path).expanduser()
        return str(credentials_path.with_name("token.json"))
    return ""


def _sanitize_redirect_uri(value: str) -> Optional[str]:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    cleaned = parsed._replace(query="", fragment="")
    return urlunparse(cleaned)


def _resolve_frontend_redirect_uri(request: Request) -> str:
    for header_name in ("referer", "origin"):
        candidate = request.headers.get(header_name)
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        path = parsed.path or "/login"
        if header_name == "origin":
            path = "/login"
        cleaned = parsed._replace(path=path, query="", fragment="")
        resolved = urlunparse(cleaned)
        sanitized = _sanitize_redirect_uri(resolved)
        if sanitized:
            return sanitized
    return SETTINGS.gmail_redirect_uri


def _fetch_google_email(credentials) -> str:
    try:
        from googleapiclient.discovery import build
    except ImportError as error:  # pragma: no cover - depends on optional extras
        raise ImportError(
            "Google API client dependencies are missing. Install "
            "'google-api-python-client' to enable Gmail auth."
        ) from error

    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    return str(profile.get("emailAddress", "")).strip().lower()


@router.post("/signup")
def signup(payload: SignupRequest):
    with session_scope() as session:
        auth_service = AuthService(session)
        try:
            auth_session = auth_service.register_user(
                email=payload.email,
                password=payload.password,
                full_name=payload.full_name,
            )
        except AuthError as error:
            return JSONResponse(
                status_code=error.status_code,
                content={"error": True, "message": error.message},
            )
    return {
        "error": False,
        "token": auth_session.token,
        "expires_at": auth_session.expires_at.isoformat(),
        "user": auth_session.user.model_dump(mode="json"),
    }


@router.post("/login")
def login(payload: LoginRequest):
    with session_scope() as session:
        auth_service = AuthService(session)
        try:
            auth_session = auth_service.authenticate(
                email=payload.email,
                password=payload.password,
            )
        except AuthError as error:
            return JSONResponse(
                status_code=error.status_code,
                content={"error": True, "message": error.message},
            )
    return {
        "error": False,
        "token": auth_session.token,
        "expires_at": auth_session.expires_at.isoformat(),
        "user": auth_session.user.model_dump(mode="json"),
    }


@router.get("/me")
def me(authorization: Optional[str] = Header(default=None)):
    token = _extract_bearer_token(authorization)
    if not token:
        return {"authenticated": False}
    with session_scope() as session:
        auth_service = AuthService(session)
        auth_session = auth_service.get_session(token)
    if auth_session is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "expires_at": auth_session.expires_at.isoformat(),
        "user": auth_session.user.model_dump(mode="json"),
    }


@router.post("/logout")
def logout(authorization: Optional[str] = Header(default=None)):
    token = _extract_bearer_token(authorization)
    if not token:
        return {"ok": False, "message": "Missing bearer token."}
    with session_scope() as session:
        auth_service = AuthService(session)
        revoked = auth_service.logout(token)
    return {"ok": revoked}


@router.get("/gmail/url")
def gmail_auth_url(request: Request):
    if not SETTINGS.gmail_credentials_path:
        return JSONResponse(
            status_code=400,
            content={"error": True, "message": "GMAIL_CREDENTIALS_PATH is not configured."},
        )
    credentials_path = Path(SETTINGS.gmail_credentials_path).expanduser()
    if not credentials_path.exists():
        return JSONResponse(
            status_code=400,
            content={"error": True, "message": "Gmail OAuth credentials file was not found."},
        )

    try:
        auth_url, state = build_authorization_url(
            str(credentials_path),
            [GMAIL_MODIFY_SCOPE],
            redirect_uri=_resolve_frontend_redirect_uri(request),
        )
    except Exception as error:
        return JSONResponse(
            status_code=400,
            content={"error": True, "message": str(error)},
        )
    return {"auth_url": auth_url, "state": state}


@router.post("/gmail/callback")
def gmail_auth_callback(payload: GmailCodeExchangeRequest, request: Request):
    if not SETTINGS.gmail_credentials_path:
        return JSONResponse(
            status_code=400,
            content={"error": True, "message": "GMAIL_CREDENTIALS_PATH is not configured."},
        )

    token_path = _resolve_gmail_token_path()
    if not token_path:
        return JSONResponse(
            status_code=400,
            content={
                "error": True,
                "message": "Unable to determine where token.json should be stored.",
            },
        )

    redirect_uri = payload.redirect_uri or _resolve_frontend_redirect_uri(request)

    try:
        credentials = exchange_code_for_token(
            SETTINGS.gmail_credentials_path,
            token_path,
            [GMAIL_MODIFY_SCOPE],
            code=payload.code,
            redirect_uri=redirect_uri,
            state=payload.state,
        )
        email = _fetch_google_email(credentials)
        if not email:
            raise AuthError("Google OAuth completed but no Gmail address was returned.", 400)

        with session_scope() as session:
            repository = InboxRepository(session)
            auth_service = AuthService(session)
            auth_session = auth_service.authenticate_or_register_oauth(
                email=email,
                full_name=email.split("@", 1)[0].replace(".", " ").title(),
            )
            connection = repository.get_provider_connection("gmail")
            updated_connection = connection.model_copy(
                update={
                    "status": "connected",
                    "account_hint": email,
                    "sync_enabled": True,
                    "dry_run_only": False,
                    "notes": "Connected through Gmail OAuth browser flow.",
                }
            )
            repository.save_provider_connection(updated_connection)
            settings = repository.get_workspace_settings()
            repository.save_workspace_settings(
                settings.model_copy(update={"preferred_provider": "gmail"})
            )
    except AuthError as error:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": True, "message": error.message},
        )
    except Exception as error:
        return JSONResponse(
            status_code=400,
            content={"error": True, "message": str(error)},
        )

    return {
        "error": False,
        "access_token": auth_session.token,
        "email": auth_session.user.email,
        "expires_at": auth_session.expires_at.isoformat(),
        "user": auth_session.user.model_dump(mode="json"),
    }
