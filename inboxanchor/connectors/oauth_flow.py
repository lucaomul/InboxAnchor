from __future__ import annotations

from pathlib import Path
from typing import Iterable


def get_credentials(credentials_path: str, token_path: str, scopes: Iterable[str]):
    """
    Load, refresh, or create OAuth credentials for Gmail API access.
    """

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as error:  # pragma: no cover - depends on optional extras
        raise ImportError(
            "Google OAuth dependencies are missing. Install "
            "'google-auth', 'google-auth-oauthlib', and 'google-api-python-client' "
            "to enable the live Gmail transport."
        ) from error

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
