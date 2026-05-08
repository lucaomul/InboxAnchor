from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from inboxanchor.agents import SafetyVerifierAgent
from inboxanchor.config.settings import SETTINGS
from inboxanchor.connectors import FakeEmailProvider, GmailClient, IMAPEmailClient, ImaplibTransport
from inboxanchor.core import IncrementalTriageEngine, TriageEngine
from inboxanchor.infra.database import init_db, session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.models import (
    EmailMessage,
    ProviderConnectionState,
    ProviderProfile,
    WorkspaceSettings,
)

logger = logging.getLogger(__name__)

PROVIDER_OPTIONS = ["fake", "gmail", "imap", "yahoo", "outlook"]
IMAP_FAMILY_PROVIDERS = {"imap", "yahoo", "outlook"}
PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "fake": ProviderProfile(
        slug="fake",
        label="Demo Workspace",
        family="demo",
        auth_mode="none",
        status="ready",
        live_ready=True,
        best_for="Guided product demos, UX checks, and deterministic testing.",
        capabilities=[
            "Seeded unread inbox",
            "Predictable action recommendations",
            "Fast 10K-scale simulation",
        ],
        safety_notes=[
            "No real mailbox access.",
            "Best choice for visual testing and regression coverage.",
        ],
    ),
    "gmail": ProviderProfile(
        slug="gmail",
        label="Gmail",
        family="gmail-api",
        auth_mode="oauth",
        status="oauth-ready",
        live_ready=False,
        best_for="Consumer or workspace Gmail inboxes once a live OAuth transport is wired.",
        capabilities=[
            "Batch triage ready",
            "Label operations supported",
            "Archive and trash action support",
        ],
        safety_notes=[
            "Requires a live Gmail API transport before production use.",
            "Full OAuth callback handling still needs the next implementation pass.",
        ],
    ),
    "imap": ProviderProfile(
        slug="imap",
        label="Generic IMAP",
        family="imap",
        auth_mode="password-or-app-password",
        status="extensible",
        live_ready=False,
        best_for="Custom mailbox experiments and generic IMAP-family development.",
        capabilities=[
            "Unified inbox abstraction",
            "Archive, read, trash, and label surface",
            "Good base for Yahoo-style connectors",
        ],
        safety_notes=[
            "Provider-specific authentication details still need real transport wiring.",
            "Use app passwords or provider-safe auth only when the live connector is added.",
        ],
    ),
    "yahoo": ProviderProfile(
        slug="yahoo",
        label="Yahoo Mail",
        family="imap",
        auth_mode="app-password",
        status="planned-live",
        live_ready=False,
        best_for="Yahoo Mail support through the IMAP-family connector path.",
        capabilities=[
            "Triage, archive, and safe cleanup path",
            "Shares the IMAP-family provider abstraction",
        ],
        safety_notes=[
            "Needs provider-specific IMAP transport and credential onboarding.",
            "Treat live delete/trash actions conservatively until transport is battle-tested.",
        ],
    ),
    "outlook": ProviderProfile(
        slug="outlook",
        label="Outlook / Microsoft",
        family="imap",
        auth_mode="app-password-or-oauth-later",
        status="planned-live",
        live_ready=False,
        best_for=(
            "Microsoft-hosted inboxes using the IMAP-family path until a richer "
            "connector lands."
        ),
        capabilities=[
            "Large-inbox triage architecture",
            "Safe approval and audit workflow",
        ],
        safety_notes=[
            (
                "A dedicated Microsoft/Graph transport would be better than generic "
                "IMAP long term."
            ),
            (
                "Use the current provider as a structured placeholder, not a "
                "production mail bridge yet."
            ),
        ],
    ),
}


def build_demo_emails() -> list[EmailMessage]:
    now = datetime.now(timezone.utc)
    return [
        EmailMessage(
            id="msg_001",
            thread_id="thr_001",
            sender="billing@vendor.com",
            subject="Invoice due tomorrow for April retainers",
            snippet="Please process the attached invoice by tomorrow.",
            body_preview=(
                "Hi team, please process the attached invoice by tomorrow "
                "to avoid service interruption."
            ),
            received_at=now - timedelta(hours=2),
            labels=["inbox"],
            has_attachments=True,
            unread=True,
        ),
        EmailMessage(
            id="msg_002",
            thread_id="thr_002",
            sender="newsletter@producthunt.com",
            subject="Your weekly newsletter digest",
            snippet="Top launches and stories from the week.",
            body_preview=(
                "This week's digest includes launch news, funding announcements, "
                "and product updates. Unsubscribe anytime."
            ),
            received_at=now - timedelta(days=1),
            labels=["inbox"],
            has_attachments=False,
            unread=True,
        ),
        EmailMessage(
            id="msg_003",
            thread_id="thr_003",
            sender="ceo@clientco.com",
            subject="Urgent: contract review before 4 PM",
            snippet="Need your review and reply today.",
            body_preview=(
                "Please review the latest contract redlines and let me know "
                "if we can approve before 4 PM."
            ),
            received_at=now - timedelta(hours=1),
            labels=["inbox"],
            has_attachments=True,
            unread=True,
        ),
        EmailMessage(
            id="msg_004",
            thread_id="thr_004",
            sender="promo@retail-brand.com",
            subject="Limited offer: 30% discount ends tonight",
            snippet="Huge sale on the products you viewed.",
            body_preview=(
                "Use your promo code before midnight for 30% off. "
                "Unsubscribe from these updates at any time."
            ),
            received_at=now - timedelta(days=20),
            labels=["inbox"],
            has_attachments=False,
            unread=True,
        ),
        EmailMessage(
            id="msg_005",
            thread_id="thr_005",
            sender="founder@startup.io",
            subject="Partnership opportunity and next steps",
            snippet="Would love to explore a partnership next week.",
            body_preview=(
                "We're interested in a partnership and would love to schedule "
                "a meeting next week if you're open."
            ),
            received_at=now - timedelta(hours=6),
            labels=["inbox"],
            has_attachments=False,
            unread=True,
        ),
        EmailMessage(
            id="msg_006",
            thread_id="thr_006",
            sender="alerts@unknown-wallet.net",
            subject="Claim now: urgent wallet verification reward",
            snippet="Winner alert. Claim now to avoid losing access.",
            body_preview=(
                "Winner alert. Claim now and verify your wallet today to avoid "
                "losing access to your funds."
            ),
            received_at=now - timedelta(days=3),
            labels=["inbox"],
            has_attachments=False,
            unread=True,
        ),
    ]


def _provider_has_live_connection(state: ProviderConnectionState) -> bool:
    return state.status in {"configured", "connected"} and state.sync_enabled


def _load_provider_connection_state(provider_name: str) -> ProviderConnectionState:
    try:
        with session_scope() as session:
            return InboxRepository(session).get_provider_connection(provider_name)
    except Exception:
        return ProviderConnectionState(provider=provider_name)


def _gmail_token_path() -> str:
    if SETTINGS.gmail_token_path:
        return SETTINGS.gmail_token_path
    if SETTINGS.gmail_credentials_path:
        credentials_path = Path(SETTINGS.gmail_credentials_path).expanduser()
        return str(credentials_path.with_name("token.json"))
    return ""


def _imap_host_for_provider(provider_name: str) -> str:
    if SETTINGS.imap_host:
        return SETTINGS.imap_host
    defaults = {
        "yahoo": "imap.mail.yahoo.com",
        "outlook": "outlook.office365.com",
    }
    return defaults.get(provider_name, "")


def _provider_can_run_live(provider_name: str, state: ProviderConnectionState) -> bool:
    if provider_name == "gmail":
        return bool(
            SETTINGS.gmail_credentials_path
            and (SETTINGS.gmail_token_path or SETTINGS.gmail_credentials_path)
            and (_provider_has_live_connection(state) or SETTINGS.gmail_credentials_path)
        )
    if provider_name in IMAP_FAMILY_PROVIDERS:
        return bool(
            SETTINGS.imap_username
            and SETTINGS.imap_password
            and _imap_host_for_provider(provider_name)
            and (_provider_has_live_connection(state) or SETTINGS.imap_username)
        )
    return provider_name == "fake"


def _build_live_gmail_provider():
    from inboxanchor.connectors.gmail_transport import GoogleAPITransport

    token_path = _gmail_token_path()
    return GmailClient(
        transport=GoogleAPITransport(
            credentials_path=SETTINGS.gmail_credentials_path,
            token_path=token_path,
        )
    )


def _build_live_imap_provider(provider_name: str):
    return ImaplibTransport(
        host=_imap_host_for_provider(provider_name),
        port=SETTINGS.imap_port,
        username=SETTINGS.imap_username,
        password=SETTINGS.imap_password,
        use_ssl=SETTINGS.imap_use_ssl,
        mailbox=SETTINGS.imap_mailbox,
        provider_name=provider_name,
        archive_mailbox=SETTINGS.imap_archive_mailbox or None,
        trash_mailbox=SETTINGS.imap_trash_mailbox or None,
    )


def build_provider(provider_name: Optional[str] = None):
    provider_name = (provider_name or SETTINGS.default_provider).lower()
    demo_emails = build_demo_emails()
    state = _load_provider_connection_state(provider_name)

    if provider_name == "gmail":
        if _provider_can_run_live(provider_name, state):
            try:
                return _build_live_gmail_provider()
            except Exception as error:  # pragma: no cover - optional dependencies/env-driven
                logger.warning("Falling back to Gmail preview provider: %s", error)
        return FakeEmailProvider(demo_emails, provider_name="gmail")
    if provider_name in IMAP_FAMILY_PROVIDERS:
        if _provider_can_run_live(provider_name, state):
            try:
                return _build_live_imap_provider(provider_name)
            except Exception as error:  # pragma: no cover - env-driven
                logger.warning(
                    "Falling back to IMAP preview provider for %s: %s",
                    provider_name,
                    error,
                )
        return IMAPEmailClient(
            seed_messages=demo_emails,
            provider_name=provider_name,
        )
    return FakeEmailProvider(demo_emails, provider_name=provider_name)


def _runtime_profile(profile: ProviderProfile) -> ProviderProfile:
    if profile.slug == "fake":
        return profile
    live_ready = _provider_can_run_live(
        profile.slug,
        _load_provider_connection_state(profile.slug),
    )
    status = "live-ready" if live_ready else profile.status
    return profile.model_copy(update={"live_ready": live_ready, "status": status})


def list_provider_profiles() -> list[ProviderProfile]:
    return [_runtime_profile(PROVIDER_PROFILES[slug]) for slug in PROVIDER_OPTIONS]


def get_provider_profile(provider_name: Optional[str]) -> ProviderProfile:
    slug = (provider_name or SETTINGS.default_provider).lower()
    return _runtime_profile(PROVIDER_PROFILES.get(slug, PROVIDER_PROFILES["fake"]))


class InboxAnchorService:
    def __init__(self, provider_name: Optional[str] = None):
        init_db()
        self.provider = build_provider(provider_name)
        base_engine = TriageEngine(
            self.provider,
            safety_verifier=SafetyVerifierAgent(),
        )
        self.engine = IncrementalTriageEngine(
            base_engine,
            provider_name=self.provider.provider_name,
        )
        self.approvals: dict[str, set[str]] = {}

    def load_workspace_settings(self) -> WorkspaceSettings:
        with session_scope() as session:
            return InboxRepository(session).get_workspace_settings()

    def save_workspace_settings(self, settings: WorkspaceSettings) -> WorkspaceSettings:
        with session_scope() as session:
            return InboxRepository(session).save_workspace_settings(settings)

    def load_provider_connection(self, provider: str) -> ProviderConnectionState:
        with session_scope() as session:
            return InboxRepository(session).get_provider_connection(provider)

    def save_provider_connection(
        self,
        state: ProviderConnectionState,
    ) -> ProviderConnectionState:
        with session_scope() as session:
            return InboxRepository(session).save_provider_connection(state)

    def approve(self, run_id: str, email_ids: list[str]) -> list[str]:
        approved = self.approvals.setdefault(run_id, set())
        approved.update(email_ids)
        return sorted(approved)

    def reject(self, run_id: str, email_ids: list[str]) -> list[str]:
        approved = self.approvals.setdefault(run_id, set())
        for email_id in email_ids:
            approved.discard(email_id)
        return sorted(approved)
