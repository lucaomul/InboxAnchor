from inboxanchor.bootstrap import InboxAnchorService, get_provider_profile, list_provider_profiles


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
