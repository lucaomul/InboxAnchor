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
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    openai_model: str = os.getenv("INBOXANCHOR_OPENAI_MODEL", "gpt-4o-mini")
    groq_model: str = os.getenv("INBOXANCHOR_GROQ_MODEL", "llama-3.1-8b-instant")
    llm_timeout_seconds: int = int(os.getenv("INBOXANCHOR_LLM_TIMEOUT_SECONDS", "30"))
    llm_retry_attempts: int = int(os.getenv("INBOXANCHOR_LLM_RETRY_ATTEMPTS", "3"))
    llm_retry_base_delay_seconds: float = float(
        os.getenv("INBOXANCHOR_LLM_RETRY_BASE_DELAY_SECONDS", "1.0")
    )
    llm_retry_max_delay_seconds: float = float(
        os.getenv("INBOXANCHOR_LLM_RETRY_MAX_DELAY_SECONDS", "30.0")
    )
    session_ttl_days: int = int(os.getenv("INBOXANCHOR_SESSION_TTL_DAYS", "30"))
    gmail_credentials_path: str = os.getenv("GMAIL_CREDENTIALS_PATH", "")
    gmail_token_path: str = os.getenv("GMAIL_TOKEN_PATH", "")
    gmail_client_id: str = os.getenv("GMAIL_CLIENT_ID", "")
    gmail_client_secret: str = os.getenv("GMAIL_CLIENT_SECRET", "")
    gmail_redirect_uri: str = os.getenv(
        "GMAIL_REDIRECT_URI",
        "http://localhost:8000/oauth/gmail/callback",
    )
    gmail_pubsub_topic: str = os.getenv("GMAIL_PUBSUB_TOPIC", "")
    gmail_watch_label_ids: str = os.getenv("GMAIL_WATCH_LABEL_IDS", "INBOX")
    gmail_fetch_workers: int = int(os.getenv("INBOXANCHOR_GMAIL_FETCH_WORKERS", "4"))
    gmail_batch_size: int = int(os.getenv("INBOXANCHOR_GMAIL_BATCH_SIZE", "100"))
    gmail_body_max_chars: int = int(os.getenv("INBOXANCHOR_GMAIL_BODY_MAX_CHARS", "50000"))
    gmail_industrial_mode: bool = _as_bool(
        os.getenv("INBOXANCHOR_GMAIL_INDUSTRIAL_MODE"),
        False,
    )
    gmail_metadata_only_first_pass: bool = _as_bool(
        os.getenv("INBOXANCHOR_GMAIL_METADATA_ONLY_FIRST_PASS"),
        True,
    )
    gmail_backfill_confidence_threshold: float = float(
        os.getenv("INBOXANCHOR_GMAIL_BACKFILL_CONFIDENCE_THRESHOLD", "0.75")
    )
    gmail_backfill_max_emails: int = int(
        os.getenv("INBOXANCHOR_GMAIL_BACKFILL_MAX_EMAILS", "500")
    )
    gmail_history_expiry_days: int = int(
        os.getenv("INBOXANCHOR_GMAIL_HISTORY_EXPIRY_DAYS", "7")
    )
    alias_managed_enabled: bool = _as_bool(
        os.getenv("INBOXANCHOR_ALIAS_MANAGED_ENABLED"),
        False,
    )
    alias_domain: str = os.getenv("INBOXANCHOR_ALIAS_DOMAIN", "")
    alias_allow_plus_fallback: bool = _as_bool(
        os.getenv("INBOXANCHOR_ALIAS_ALLOW_PLUS_FALLBACK"),
        False,
    )
    alias_resolver_secret: str = os.getenv("INBOXANCHOR_ALIAS_RESOLVER_SECRET", "")
    alias_inbound_ready: bool = _as_bool(
        os.getenv("INBOXANCHOR_ALIAS_INBOUND_READY"),
        False,
    )
    imap_host: str = os.getenv("IMAP_HOST", "")
    imap_port: int = int(os.getenv("IMAP_PORT", "993"))
    imap_username: str = os.getenv("IMAP_USERNAME", "")
    imap_password: str = os.getenv("IMAP_PASSWORD", "")
    imap_use_ssl: bool = _as_bool(os.getenv("IMAP_USE_SSL"), True)
    imap_mailbox: str = os.getenv("IMAP_MAILBOX", "INBOX")
    imap_archive_mailbox: str = os.getenv("IMAP_ARCHIVE_MAILBOX", "")
    imap_trash_mailbox: str = os.getenv("IMAP_TRASH_MAILBOX", "")


SETTINGS = Settings()
