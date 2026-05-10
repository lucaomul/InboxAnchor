from inboxanchor.bootstrap import InboxAnchorService, get_provider_profile, list_provider_profiles
from inboxanchor.connectors.imap_transport import ImaplibTransport
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.models import IMAPConnectionState, ProviderConnectionState


def test_provider_profiles_are_available_for_supported_providers():
    profiles = list_provider_profiles()

    assert len(profiles) >= 5
    assert get_provider_profile("gmail").auth_mode == "oauth"
    assert get_provider_profile("fake").live_ready is True
    assert get_provider_profile("outlook").family == "imap"


def test_service_exposes_workspace_and_provider_state_helpers():
    service = InboxAnchorService()

    settings = service.load_workspace_settings()
    connection = service.load_provider_connection("gmail")

    assert settings.preferred_provider == "fake"
    assert connection.provider == "gmail"


def test_gmail_service_uses_safe_preview_provider_until_live_transport_exists():
    service = InboxAnchorService(provider_name="gmail")

    emails = service.provider.list_unread(limit=3)

    assert service.provider.provider_name == "gmail"
    assert len(emails) == 3


def test_yahoo_service_uses_owner_scoped_imap_credentials_when_available():
    owner_email = "imap-owner@example.com"
    with session_scope() as session:
        repository = InboxRepository(session)
        repository.save_provider_connection(
            ProviderConnectionState(
                provider="yahoo",
                status="connected",
                account_hint="owner@yahoo.com",
                sync_enabled=True,
                dry_run_only=False,
                imap=IMAPConnectionState(
                    host="imap.mail.yahoo.com",
                    port=993,
                    username="owner@yahoo.com",
                    use_ssl=True,
                    mailbox="INBOX",
                    archive_mailbox="Archive",
                    trash_mailbox="Trash",
                ),
            ),
            owner_email=owner_email,
        )
        repository.save_provider_secret(
            "yahoo",
            {"password": "owner-yahoo-app-password"},
            owner_email=owner_email,
        )

    service = InboxAnchorService(provider_name="yahoo", owner_email=owner_email)
    connection = service.load_provider_connection("yahoo")

    assert isinstance(service.provider, ImaplibTransport)
    assert service.provider.provider_name == "yahoo"
    assert service.provider.username == "owner@yahoo.com"
    assert service.provider.password == "owner-yahoo-app-password"
    assert connection.imap is not None
    assert connection.imap.password_configured is True
