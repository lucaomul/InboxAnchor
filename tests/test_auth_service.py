from __future__ import annotations

from inboxanchor.infra.auth import AuthError, AuthService, hash_password, verify_password
from inboxanchor.infra.database import session_scope


def test_password_hash_and_verify_roundtrip():
    hashed = hash_password("super-secret-pass")

    assert hashed != "super-secret-pass"
    assert verify_password("super-secret-pass", hashed) is True
    assert verify_password("wrong-pass", hashed) is False


def test_register_login_and_logout_flow():
    with session_scope() as session:
        auth = AuthService(session)
        created = auth.register_user(
            full_name="Luca Craciun",
            email="luca@example.com",
            password="super-secret-pass",
        )
        session_token = created.token
        assert created.user.email == "luca@example.com"

    with session_scope() as session:
        auth = AuthService(session)
        restored = auth.get_session(session_token)
        assert restored is not None
        assert restored.user.full_name == "Luca Craciun"

    with session_scope() as session:
        auth = AuthService(session)
        logged_in = auth.authenticate(
            email="luca@example.com",
            password="super-secret-pass",
        )
        assert logged_in.user.email == "luca@example.com"

    with session_scope() as session:
        auth = AuthService(session)
        assert auth.logout(session_token) is True
        assert auth.get_session(session_token) is None


def test_register_rejects_duplicate_email():
    with session_scope() as session:
        auth = AuthService(session)
        auth.register_user(
            full_name="Luca Craciun",
            email="luca@example.com",
            password="super-secret-pass",
        )

    with session_scope() as session:
        auth = AuthService(session)
        try:
            auth.register_user(
                full_name="Luca Craciun",
                email="luca@example.com",
                password="another-secret",
            )
        except AuthError as error:
            assert error.status_code == 409
        else:  # pragma: no cover - defensive
            raise AssertionError("Expected duplicate account registration to fail.")
