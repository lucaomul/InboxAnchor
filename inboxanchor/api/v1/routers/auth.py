from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from inboxanchor.infra.auth import AuthError, AuthService
from inboxanchor.infra.database import session_scope

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    full_name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


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
