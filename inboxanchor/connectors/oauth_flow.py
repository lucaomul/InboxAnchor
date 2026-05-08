from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional


def _import_google_oauth():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import Flow, InstalledAppFlow
    except ImportError as error:  # pragma: no cover - depends on optional extras
        raise ImportError(
            "Google OAuth dependencies are missing. Install "
            "'google-auth', 'google-auth-oauthlib', and 'google-api-python-client' "
            "to enable the live Gmail transport."
        ) from error
    return Request, Credentials, Flow, InstalledAppFlow


def get_credentials(credentials_path: str, token_path: str, scopes: Iterable[str]):
    """
    Load, refresh, or create OAuth credentials for Gmail API access.
    """

    Request, Credentials, _, InstalledAppFlow = _import_google_oauth()

    scopes = list(scopes)
    credentials_file = Path(credentials_path).expanduser()
    token_file = Path(token_path).expanduser()
    token_file.parent.mkdir(parents=True, exist_ok=True)

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
            creds = flow.run_local_server(port=0)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return creds


def build_authorization_url(
    credentials_path: str,
    scopes: Iterable[str],
    *,
    redirect_uri: str,
    state: Optional[str] = None,
) -> tuple[str, str]:
    _, _, Flow, _ = _import_google_oauth()
    flow = Flow.from_client_secrets_file(str(Path(credentials_path).expanduser()), scopes=scopes)
    flow.redirect_uri = redirect_uri
    authorization_url, resolved_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return authorization_url, resolved_state


def exchange_code_for_token(
    credentials_path: str,
    token_path: str,
    scopes: Iterable[str],
    *,
    code: str,
    redirect_uri: str,
    state: Optional[str] = None,
):
    _, _, Flow, _ = _import_google_oauth()
    token_file = Path(token_path).expanduser()
    token_file.parent.mkdir(parents=True, exist_ok=True)

    flow = Flow.from_client_secrets_file(str(Path(credentials_path).expanduser()), scopes=scopes)
    flow.redirect_uri = redirect_uri
    if state:
        flow.oauth2session.state = state
    flow.fetch_token(code=code)
    creds = flow.credentials
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds
