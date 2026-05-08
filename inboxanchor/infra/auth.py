from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from inboxanchor.config.settings import SETTINGS
from inboxanchor.infra.database import AccountUserORM, AuthSessionORM
from inboxanchor.models import AccountUser, AuthSession

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 240000
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class AuthError(Exception):
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user_model(row: AccountUserORM) -> AccountUser:
    return AccountUser(
        id=row.id,
        email=row.email,
        full_name=row.full_name,
        plan=row.plan,
        is_active=row.is_active,
        created_at=_ensure_utc(row.created_at),
        last_login_at=_ensure_utc(row.last_login_at),
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return f"{PASSWORD_ALGORITHM}${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != PASSWORD_ALGORITHM:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    ).hex()
    return hmac.compare_digest(digest, digest_hex)


class AuthService:
    def __init__(self, session):
        self.session = session

    def register_user(self, *, email: str, password: str, full_name: str) -> AuthSession:
        normalized_email = _normalize_email(email)
        cleaned_name = full_name.strip()
        self._validate_signup(normalized_email, password, cleaned_name)

        existing = self.session.scalar(
            select(AccountUserORM).where(AccountUserORM.email == normalized_email)
        )
        if existing is not None:
            raise AuthError("An account with this email already exists.", status_code=409)

        user = AccountUserORM(
            email=normalized_email,
            full_name=cleaned_name,
            password_hash=hash_password(password),
            plan="founder",
        )
        self.session.add(user)
        self.session.flush()
        return self._issue_session(user)

    def authenticate(self, *, email: str, password: str) -> AuthSession:
        normalized_email = _normalize_email(email)
        user = self.session.scalar(
            select(AccountUserORM).where(AccountUserORM.email == normalized_email)
        )
        if user is None or not verify_password(password, user.password_hash):
            raise AuthError("Invalid email or password.", status_code=401)
        if not user.is_active:
            raise AuthError("This account is disabled.", status_code=403)
        return self._issue_session(user)

    def authenticate_or_register_oauth(
        self,
        *,
        email: str,
        full_name: Optional[str] = None,
    ) -> AuthSession:
        normalized_email = _normalize_email(email)
        user = self.session.scalar(
            select(AccountUserORM).where(AccountUserORM.email == normalized_email)
        )
        if user is None:
            inferred_name = (
                (full_name or normalized_email.split("@", 1)[0]).strip()
                or "InboxAnchor User"
            )
            user = AccountUserORM(
                email=normalized_email,
                full_name=inferred_name,
                password_hash=hash_password(secrets.token_urlsafe(24)),
                plan="founder",
            )
            self.session.add(user)
            self.session.flush()
        elif full_name and full_name.strip() and user.full_name != full_name.strip():
            user.full_name = full_name.strip()

        if not user.is_active:
            raise AuthError("This account is disabled.", status_code=403)
        return self._issue_session(user)

    def get_session(self, token: str) -> Optional[AuthSession]:
        if not token:
            return None
        token_hash = _hash_session_token(token)
        row = self.session.scalar(
            select(AuthSessionORM).where(AuthSessionORM.token_hash == token_hash)
        )
        expires_at = _ensure_utc(row.expires_at) if row is not None else None
        revoked_at = _ensure_utc(row.revoked_at) if row is not None else None
        if row is None or revoked_at is not None or expires_at <= _utcnow():
            return None
        user = self.session.get(AccountUserORM, row.user_id)
        if user is None or not user.is_active:
            return None
        row.last_seen_at = _utcnow()
        return AuthSession(
            token=token,
            user=_user_model(user),
            created_at=_ensure_utc(row.created_at),
            expires_at=expires_at,
        )

    def logout(self, token: str) -> bool:
        if not token:
            return False
        token_hash = _hash_session_token(token)
        row = self.session.scalar(
            select(AuthSessionORM).where(AuthSessionORM.token_hash == token_hash)
        )
        if row is None:
            return False
        row.revoked_at = _utcnow()
        row.last_seen_at = _utcnow()
        return True

    def _issue_session(self, user: AccountUserORM) -> AuthSession:
        raw_token = secrets.token_urlsafe(32)
        now = _utcnow()
        user.last_login_at = now
        session_row = AuthSessionORM(
            user_id=user.id,
            token_hash=_hash_session_token(raw_token),
            created_at=now,
            expires_at=now + timedelta(days=SETTINGS.session_ttl_days),
            last_seen_at=now,
        )
        self.session.add(session_row)
        self.session.flush()
        return AuthSession(
            token=raw_token,
            user=_user_model(user),
            created_at=session_row.created_at,
            expires_at=session_row.expires_at,
        )

    def _validate_signup(self, email: str, password: str, full_name: str) -> None:
        if not EMAIL_PATTERN.match(email):
            raise AuthError("Enter a valid email address.", status_code=400)
        if len(password) < 8:
            raise AuthError("Password must be at least 8 characters.", status_code=400)
        if len(full_name) < 2:
            raise AuthError("Full name must be at least 2 characters.", status_code=400)
