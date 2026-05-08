from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_database_url() -> str:
    app_dir = Path(
        os.getenv(
            "INBOXANCHOR_DATA_DIR",
            str(Path(tempfile.gettempdir()) / "inboxanchor"),
        )
    )
    return f"sqlite:///{app_dir / 'inboxanchor.db'}"


@dataclass
class Settings:
    environment: str = os.getenv("INBOXANCHOR_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", _default_database_url())
    default_provider: str = os.getenv("INBOXANCHOR_DEFAULT_PROVIDER", "fake")
    dry_run_default: bool = _as_bool(os.getenv("INBOXANCHOR_DRY_RUN"), True)
    llm_provider: str = os.getenv("INBOXANCHOR_LLM_PROVIDER", "mock")
    llm_timeout_seconds: int = int(os.getenv("INBOXANCHOR_LLM_TIMEOUT_SECONDS", "15"))
    llm_retry_attempts: int = int(os.getenv("INBOXANCHOR_LLM_RETRY_ATTEMPTS", "2"))
    gmail_client_id: str = os.getenv("GMAIL_CLIENT_ID", "")
    gmail_client_secret: str = os.getenv("GMAIL_CLIENT_SECRET", "")
    gmail_redirect_uri: str = os.getenv(
        "GMAIL_REDIRECT_URI",
        "http://localhost:8000/oauth/gmail/callback",
    )
    imap_host: str = os.getenv("IMAP_HOST", "")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_username: str = os.getenv("IMAP_USERNAME", "")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")
    imap_use_ssl: bool = _as_bool(os.getenv("IMAP_USE_SSL"), True)


SETTINGS = Settings()
