import os
from datetime import datetime, timezone
from pathlib import Path

from inboxanchor.bootstrap import build_demo_emails
from inboxanchor.infra.database import _resolve_database_url, _sqlite_connect_args, session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.models import EmailAlias, EmailAliasStatus


def test_relative_sqlite_url_resolves_to_app_data_directory():
    resolved = _resolve_database_url("sqlite:///./inboxanchor.db")

    assert resolved.startswith("sqlite:///")
    expected_dir = os.getenv("INBOXANCHOR_DATA_DIR", "")
    assert resolved.endswith("/inboxanchor.db")
    assert expected_dir in resolved


def test_absolute_sqlite_url_is_preserved_when_parent_is_writable(tmp_path):
    candidate = tmp_path / "nested" / "inboxanchor.db"

    resolved = _resolve_database_url(f"sqlite:///{candidate}")

    assert resolved == f"sqlite:///{candidate}"
    assert Path(candidate.parent).exists()


def test_sqlite_connect_args_enable_busy_timeout_and_cross_thread_access():
    connect_args = _sqlite_connect_args()

    assert connect_args["check_same_thread"] is False
    assert connect_args["timeout"] == 30


def test_mailbox_cache_preserves_existing_full_body_on_metadata_refresh():
    seed = build_demo_emails()[0].model_copy(
        update={
            "id": "cache-preserve-1",
            "body_preview": "Preview snippet",
            "body_full": "The original full body should stay available.",
        }
    )
    metadata_only = seed.model_copy(
        update={
            "snippet": "Updated preview snippet",
            "body_preview": "Updated preview snippet",
            "body_full": "",
        }
    )

    with session_scope() as session:
        repository = InboxRepository(session)
        repository.upsert_mailbox_email("cache-preserve", seed)

    with session_scope() as session:
        repository = InboxRepository(session)
        repository.upsert_mailbox_email("cache-preserve", metadata_only)
        cached = repository.get_mailbox_email("cache-preserve", "cache-preserve-1")
        sender_profile = repository.get_sender_profile("cache-preserve", seed.sender)

    assert cached is not None
    assert cached["body_preview"] == "Updated preview snippet"
    assert cached["body_full"] == "The original full body should stay available."
    assert sender_profile is not None
    assert sender_profile["total_messages"] == 1


def test_mailbox_cache_can_hydrate_full_body_after_lightweight_sync():
    seed = build_demo_emails()[1].model_copy(
        update={
            "id": "cache-hydrate-1",
            "body_preview": "Short preview only",
            "body_full": "",
        }
    )

    with session_scope() as session:
        repository = InboxRepository(session)
        repository.upsert_mailbox_email("cache-hydrate", seed)

    with session_scope() as session:
        repository = InboxRepository(session)
        hydrated = repository.save_mailbox_email_body(
            "cache-hydrate",
            "cache-hydrate-1",
            body_full="This is the hydrated full body for the cached email.",
        )

    assert hydrated is not None
    assert hydrated["body_full"] == "This is the hydrated full body for the cached email."
    assert hydrated["body_preview"] == "This is the hydrated full body for the cached email."[:500]


def test_mailbox_cache_builds_sender_and_domain_profiles():
    github_email = build_demo_emails()[0].model_copy(
        update={
            "id": "sender-profile-1",
            "thread_id": "sender-profile-1",
            "sender": "notifications@github.com",
            "subject": "[lucaomul/InboxAnchor] Pull request #42 needs review",
            "snippet": "GitHub opened a pull request review request on your repo.",
            "body_preview": "GitHub requested a review on InboxAnchor and linked the checks.",
        }
    )

    with session_scope() as session:
        repository = InboxRepository(session)
        repository.upsert_mailbox_email("gmail", github_email)

    with session_scope() as session:
        repository = InboxRepository(session)
        sender_profile = repository.get_sender_profile("gmail", "notifications@github.com")
        domain_profile = repository.get_domain_profile("gmail", "github.com")

    assert sender_profile is not None
    assert sender_profile["sender_address"] == "notifications@github.com"
    assert sender_profile["total_messages"] == 1
    assert sender_profile["work_messages"] == 1
    assert sender_profile["automated_messages"] == 1
    assert sender_profile["archetype"] == "dev_tooling"
    assert domain_profile is not None
    assert domain_profile["domain"] == "github.com"
    assert domain_profile["work_messages"] == 1


def test_provider_sync_state_roundtrip_and_clear():
    with session_scope() as session:
        repository = InboxRepository(session)
        stored = repository.save_provider_sync_state(
            "gmail",
            "mailbox_backfill",
            {
                "target_count": 20000,
                "processed_count": 2500,
                "next_offset": 2500,
                "completed": False,
            },
        )

    assert stored["processed_count"] == 2500
    assert stored["sync_kind"] == "mailbox_backfill"

    with session_scope() as session:
        repository = InboxRepository(session)
        loaded = repository.get_provider_sync_state("gmail", "mailbox_backfill")

    assert loaded is not None
    assert loaded["target_count"] == 20000
    assert loaded["next_offset"] == 2500
    assert loaded["completed"] is False

    with session_scope() as session:
        repository = InboxRepository(session)
        repository.clear_provider_sync_state("gmail", "mailbox_backfill")

    with session_scope() as session:
        repository = InboxRepository(session)
        cleared = repository.get_provider_sync_state("gmail", "mailbox_backfill")

    assert cleared is None


def test_alias_repository_helpers_support_lookup_list_and_revoke():
    alias = EmailAlias(
        owner_email="alias-owner@example.com",
        provider="gmail",
        alias_address="travel@inboxanchor.com",
        target_email="alias-owner@example.com",
        alias_type="managed",
        label="travel",
        purpose="airlines",
        note="Alias for travel bookings.",
        status=EmailAliasStatus.active,
        created_at=datetime.now(timezone.utc),
    )

    with session_scope() as session:
        repository = InboxRepository(session)
        stored = repository.create_alias(alias)

    assert stored.alias_address == "travel@inboxanchor.com"

    with session_scope() as session:
        repository = InboxRepository(session)
        looked_up = repository.get_alias_by_address("travel@inboxanchor.com")
        listed = repository.list_aliases(owner_email="alias-owner@example.com")

    assert looked_up is not None
    assert looked_up.owner_email == "alias-owner@example.com"
    assert len(listed) == 1
    assert listed[0].alias_address == "travel@inboxanchor.com"

    with session_scope() as session:
        repository = InboxRepository(session)
        revoked = repository.revoke_alias("travel@inboxanchor.com")

    assert revoked is not None
    assert revoked.status == EmailAliasStatus.revoked
    assert revoked.revoked_at is not None


def test_provider_sync_state_preserves_full_mailbox_without_target_count():
    with session_scope() as session:
        repository = InboxRepository(session)
        stored = repository.save_provider_sync_state(
            "gmail",
            "mailbox_backfill",
            {
                "target_count": None,
                "full_mailbox": True,
                "processed_count": 42000,
                "next_offset": 42000,
                "completed": True,
            },
        )

    assert stored["processed_count"] == 42000
    assert stored["full_mailbox"] is True
    assert "target_count" not in stored or stored["target_count"] in (None, 0)

    with session_scope() as session:
        repository = InboxRepository(session)
        loaded = repository.get_provider_sync_state("gmail", "mailbox_backfill")

    assert loaded is not None
    assert loaded["full_mailbox"] is True
    assert loaded["processed_count"] == 42000
    assert loaded["next_offset"] == 42000
    assert "target_count" not in loaded or loaded["target_count"] in (None, 0)
