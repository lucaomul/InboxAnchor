import base64
import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Optional

from fastapi.testclient import TestClient

import inboxanchor.api.main as api_main
import inboxanchor.api.v1.routers.auth as auth_router
import inboxanchor.api.v1.routers.frontend as frontend_router
import inboxanchor.api.v1.routers.oauth as oauth_router
from inboxanchor.api.main import app
from inboxanchor.bootstrap import build_demo_emails

client = TestClient(app)


def test_api_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_cors_preflight_allows_local_frontend_origin():
    response = client.options(
        "/ops/overview",
        headers={
            "Origin": "http://127.0.0.1:4173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:4173"


def test_cors_preflight_allows_react_frontend_dev_origin():
    response = client.options(
        "/ops/overview",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:8080"


def test_auth_signup_login_me_and_logout_flow():
    signup = client.post(
        "/auth/signup",
        json={
            "full_name": "Luca Craciun",
            "email": "luca@example.com",
            "password": "super-secret-pass",
        },
    )

    assert signup.status_code == 200
    token = signup.json()["token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert me.json()["user"]["email"] == "luca@example.com"

    logout = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200
    assert logout.json()["ok"] is True

    post_logout = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert post_logout.status_code == 200
    assert post_logout.json()["authenticated"] is False

    login = client.post(
        "/auth/login",
        json={"email": "luca@example.com", "password": "super-secret-pass"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["full_name"] == "Luca Craciun"


def test_auth_signup_rejects_duplicate_email():
    first = client.post(
        "/auth/signup",
        json={
            "full_name": "Luca Craciun",
            "email": "luca@example.com",
            "password": "super-secret-pass",
        },
    )
    duplicate = client.post(
        "/auth/signup",
        json={
            "full_name": "Luca Craciun",
            "email": "luca@example.com",
            "password": "super-secret-pass",
        },
    )

    assert first.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] is True


def test_providers_endpoint_exposes_provider_profiles():
    response = client.get("/providers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 5
    assert any(item["slug"] == "gmail" for item in payload["items"])
    assert any(item["slug"] == "outlook" for item in payload["items"])
    assert all("connection" in item for item in payload["items"])


def test_workspace_settings_roundtrip_and_triage_uses_saved_defaults():
    save_response = client.put(
        "/settings/workspace",
        json={
            "preferred_provider": "outlook",
            "dry_run_default": True,
            "default_scan_limit": 300,
            "default_batch_size": 500,
            "default_confidence_threshold": 0.8,
            "default_email_preview_limit": 80,
            "default_recommendation_preview_limit": 90,
            "follow_up_radar_enabled": True,
            "follow_up_after_hours": 36,
            "follow_up_priority_floor": "high",
            "onboarding_completed": True,
            "operator_mode": "balanced",
            "policy": {
                "allow_newsletter_mark_read": True,
                "newsletter_confidence_threshold": 0.95,
                "allow_promo_archive": True,
                "promo_archive_age_days": 14,
                "allow_low_priority_cleanup": True,
                "low_priority_age_days": 7,
                "allow_spam_trash_recommendations": True,
                "auto_label_recommendations": True,
                "require_review_for_attachments": True,
                "require_review_for_finance": True,
                "require_review_for_personal": True,
            },
        },
    )
    settings_response = client.get("/settings/workspace")
    run_response = client.post("/triage/run", json={})

    assert save_response.status_code == 200
    assert settings_response.status_code == 200
    assert settings_response.json()["preferred_provider"] == "outlook"
    assert settings_response.json()["follow_up_after_hours"] == 36
    assert settings_response.json()["follow_up_priority_floor"] == "high"
    assert run_response.status_code == 200
    payload = run_response.json()
    assert payload["provider"] == "outlook"
    assert payload["batch_size"] == 500
    assert payload["email_preview_limit"] == 80
    assert payload["recommendation_preview_limit"] == 90


def test_api_dry_run_triage_defaults_safe():
    response = client.post("/triage/run", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["recommendations"]
    assert payload["batch_size"] == 250


def test_gmail_triage_runs_in_safe_preview_mode_until_transport_is_live():
    response = client.post("/triage/run", json={"provider": "gmail", "limit": 10})

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "gmail"
    assert payload["recommendations"]


def test_approval_flow_and_execution():
    run_response = client.post("/triage/run", json={"dry_run": False, "limit": 10})
    payload = run_response.json()
    run_id = payload["run_id"]
    target = next(
        rec
        for rec in payload["recommendations"]
        if rec["status"] == "requires_approval"
        and rec["recommended_action"] != "trash"
    )

    approve_response = client.post(
        "/actions/approve",
        json={"run_id": run_id, "email_ids": [target["email_id"]]},
    )
    execute_response = client.post("/actions/execute", json={"run_id": run_id})

    assert approve_response.status_code == 200
    assert execute_response.status_code == 200
    executed = execute_response.json()["executed"]
    assert any(item["email_id"] == target["email_id"] for item in executed)


def test_destructive_action_blocked_without_confirmation():
    run_response = client.post("/triage/run", json={"dry_run": False, "limit": 10})
    payload = run_response.json()
    run_id = payload["run_id"]
    target = next(rec for rec in payload["recommendations"] if rec["recommended_action"] == "trash")

    client.post("/actions/approve", json={"run_id": run_id, "email_ids": [target["email_id"]]})
    execute_response = client.post("/actions/execute", json={"run_id": run_id})

    assert execute_response.status_code == 200
    executed = execute_response.json()["executed"]
    spam_decision = next(item for item in executed if item["email_id"] == target["email_id"])
    assert spam_decision["final_action"] == "blocked"


def test_provider_connection_roundtrip():
    save_response = client.put(
        "/providers/gmail/connection",
        json={
            "status": "configured",
            "account_hint": "ops@company.com",
            "sync_enabled": True,
            "dry_run_only": False,
            "notes": "OAuth callback staged for next pass.",
        },
    )
    get_response = client.get("/providers/gmail/connection")

    assert save_response.status_code == 200
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload["provider"] == "gmail"
    assert payload["status"] == "configured"
    assert payload["sync_enabled"] is True


def test_follow_up_reminders_can_be_created_rescheduled_and_completed():
    create_response = client.post(
        "/reminders",
        json={
            "provider": "fake",
            "email_id": "msg_003",
            "owner_email": "luca@example.com",
            "sender": "ceo@clientco.com",
            "subject": "Urgent: contract review before 4 PM",
            "preview": "Please review the latest contract redlines.",
            "priority": "high",
            "category": "work",
            "note": "Follow up if no answer arrives.",
            "due_in_hours": 4,
        },
    )

    assert create_response.status_code == 200
    first_payload = create_response.json()
    assert first_payload["status"] == "active"

    reschedule_response = client.post(
        "/reminders",
        json={
            "provider": "fake",
            "email_id": "msg_003",
            "owner_email": "luca@example.com",
            "sender": "ceo@clientco.com",
            "subject": "Urgent: contract review before 4 PM",
            "preview": "Please review the latest contract redlines.",
            "priority": "high",
            "category": "work",
            "note": "Push this to tomorrow morning.",
            "due_in_hours": 24,
        },
    )

    assert reschedule_response.status_code == 200
    rescheduled_payload = reschedule_response.json()
    assert rescheduled_payload["id"] == first_payload["id"]
    assert rescheduled_payload["note"] == "Push this to tomorrow morning."

    list_response = client.get(
        "/reminders",
        params={"owner_email": "luca@example.com", "status": "active"},
    )
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1

    complete_response = client.post(f"/reminders/{first_payload['id']}/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"

    active_after = client.get(
        "/reminders",
        params={"owner_email": "luca@example.com", "status": "active"},
    )
    completed_after = client.get(
        "/reminders",
        params={"owner_email": "luca@example.com", "status": "completed"},
    )
    assert active_after.json()["count"] == 0
    assert completed_after.json()["count"] == 1


def test_triage_pagination_endpoints_expose_totals():
    run_response = client.post(
        "/triage/run",
        json={"provider": "outlook", "dry_run": True, "limit": 10, "email_preview_limit": 25},
    )
    payload = run_response.json()
    run_id = payload["run_id"]

    runs_response = client.get("/triage")
    emails_response = client.get(f"/triage/{run_id}/emails", params={"limit": 2, "offset": 0})
    recommendations_response = client.get(
        f"/triage/{run_id}/recommendations",
        params={"limit": 2, "offset": 0},
    )
    email_detail_response = client.get(
        f"/triage/{run_id}/email-details",
        params={"limit": 2, "offset": 0, "priority": "all", "category": "all"},
    )
    recommendation_detail_response = client.get(
        f"/triage/{run_id}/recommendation-details",
        params={"limit": 2, "offset": 0, "status": "all"},
    )

    assert runs_response.status_code == 200
    assert any(item["run_id"] == run_id for item in runs_response.json()["items"])
    assert emails_response.status_code == 200
    assert emails_response.json()["total"] >= emails_response.json()["count"]
    assert recommendations_response.status_code == 200
    assert recommendations_response.json()["total"] >= recommendations_response.json()["count"]
    assert email_detail_response.status_code == 200
    assert email_detail_response.json()["items"][0]["classification"]["priority"]
    assert recommendation_detail_response.status_code == 200
    assert recommendation_detail_response.json()["items"][0]["email"]["subject"]


def test_execute_uses_provider_from_stored_run(mocker):
    run_response = client.post(
        "/triage/run",
        json={"provider": "outlook", "dry_run": False, "limit": 10},
    )
    payload = run_response.json()
    run_id = payload["run_id"]
    target = next(
        rec
        for rec in payload["recommendations"]
        if rec["status"] == "requires_approval"
        and rec["recommended_action"] != "trash"
    )
    client.post("/actions/approve", json={"run_id": run_id, "email_ids": [target["email_id"]]})

    original_service = api_main.InboxAnchorService
    provider_calls: list[Optional[str]] = []

    def recording_service(provider_name=None):
        provider_calls.append(provider_name)
        return original_service(provider_name=provider_name)

    mocker.patch.object(api_main, "InboxAnchorService", side_effect=recording_service)
    execute_response = client.post("/actions/execute", json={"run_id": run_id})

    assert execute_response.status_code == 200
    assert provider_calls[-1] == "outlook"


def test_gmail_webhook_route_accepts_pubsub_payload():
    encoded = base64.urlsafe_b64encode(
        json.dumps({"emailAddress": "ops@example.com", "historyId": "12345"}).encode("utf-8")
    ).decode("utf-8")

    response = client.post(
        "/webhooks/gmail",
        json={
            "message": {
                "data": encoded,
                "messageId": "msg-1",
                "publishTime": "2026-05-08T10:00:00Z",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["notification"]["history_id"] == "12345"


def test_gmail_oauth_start_returns_authorization_url(monkeypatch, tmp_path):
    credentials_path = tmp_path / "credentials.json"
    credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(oauth_router.SETTINGS, "gmail_credentials_path", str(credentials_path))
    monkeypatch.setattr(
        oauth_router,
        "build_authorization_url",
        lambda *args, **kwargs: (
            "https://accounts.google.com/test-auth",
            "state-123",
            "verifier-123",
        ),
    )

    response = client.get("/oauth/gmail/start")

    assert response.status_code == 200
    assert response.json()["auth_url"] == "https://accounts.google.com/test-auth"


def test_gmail_oauth_callback_updates_provider_state(monkeypatch, tmp_path):
    credentials_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"
    credentials_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(oauth_router.SETTINGS, "gmail_credentials_path", str(credentials_path))
    monkeypatch.setattr(oauth_router.SETTINGS, "gmail_token_path", str(token_path))
    oauth_payload: dict[str, str | None] = {}
    monkeypatch.setattr(
        oauth_router,
        "exchange_code_for_token",
        lambda *args, **kwargs: oauth_payload.update(
            {"state": kwargs.get("state"), "code_verifier": kwargs.get("code_verifier")}
        )
        or object(),
    )
    oauth_router.GMAIL_PKCE_REGISTRY["demo"] = "oauth-verifier"

    response = client.get("/oauth/gmail/callback", params={"code": "demo-code", "state": "demo"})
    connection = client.get("/providers/gmail/connection")

    assert response.status_code == 200
    assert "Gmail connected successfully" in response.text
    assert connection.status_code == 200
    assert connection.json()["status"] == "connected"
    assert oauth_payload["state"] == "demo"
    assert oauth_payload["code_verifier"] == "oauth-verifier"
    assert connection.json()["sync_enabled"] is True


def test_frontend_compat_endpoints_expose_react_contract():
    frontend_router.FRONTEND_RUN_CACHE.clear()
    frontend_router.FRONTEND_SERVICE_CACHE.clear()
    frontend_router.FRONTEND_BLOCK_REGISTRY.clear()
    frontend_router.FRONTEND_FORCE_REFRESH_PROVIDERS.clear()
    frontend_router.FRONTEND_PROVIDER_ERRORS.clear()

    emails_response = client.get("/emails")
    classifications_response = client.get("/classifications")
    recommendations_response = client.get("/recommendations")
    digest_response = client.get("/digest")
    webhook_health_response = client.get("/health/webhook")

    assert emails_response.status_code == 200
    emails_payload = emails_response.json()
    assert emails_payload["total"] >= len(emails_payload["emails"]) > 0
    first_email = emails_payload["emails"][0]
    assert {
        "id",
        "threadId",
        "sender",
        "subject",
        "bodyPreview",
        "bodyFull",
        "receivedAt",
        "hasAttachments",
    } <= set(first_email.keys())
    assert first_email["bodyFull"]

    assert classifications_response.status_code == 200
    classifications = classifications_response.json()
    assert first_email["id"] in classifications
    assert classifications[first_email["id"]]["priority"] in {"critical", "high", "medium", "low"}

    assert recommendations_response.status_code == 200
    recommendation = recommendations_response.json()[0]
    assert {"emailId", "recommendedAction", "status", "requiresApproval", "proposedLabels"} <= set(
        recommendation.keys()
    )

    actions_response = client.get(f"/emails/{first_email['id']}/actions")
    assert actions_response.status_code == 200
    assert isinstance(actions_response.json(), list)

    email_detail_response = client.get(f"/emails/{first_email['id']}")
    assert email_detail_response.status_code == 200
    assert {"replyDraft", "canReply", "replyToAddress"} <= set(email_detail_response.json().keys())

    assert digest_response.status_code == 200
    assert digest_response.json()["totalUnread"] >= 1

    assert webhook_health_response.status_code == 200
    assert webhook_health_response.json()["status"] == "healthy"


def test_frontend_apply_and_block_routes_update_recommendation_state():
    recommendations = client.get("/recommendations").json()
    safe = next(item for item in recommendations if item["status"] == "safe")
    review = next(item for item in recommendations if item["status"] == "requires_approval")

    apply_response = client.post(
        f"/recommendations/{safe['emailId']}/apply",
        json={"action": safe["recommendedAction"]},
    )
    assert apply_response.status_code == 200
    emails_after_apply = client.get("/emails").json()["emails"]
    assert safe["emailId"] not in [item["id"] for item in emails_after_apply]

    block_response = client.post(
        f"/recommendations/{review['emailId']}/block",
        json={"action": review["recommendedAction"]},
    )
    assert block_response.status_code == 200
    recommendations_after_block = client.get("/recommendations").json()
    blocked_item = next(
        item
        for item in recommendations_after_block
        if item["emailId"] == review["emailId"]
    )
    assert blocked_item["status"] == "blocked"


def test_frontend_emails_include_classification_and_apply_server_side_filters():
    all_emails_response = client.get("/emails", params={"limit": 10})
    assert all_emails_response.status_code == 200
    all_payload = all_emails_response.json()
    assert all_payload["emails"]
    assert "classification" in all_payload["emails"][0]
    subject_tokens = [
        token.strip(".,:;!?()[]{}").lower()
        for token in all_payload["emails"][0]["subject"].split()
        if len(token.strip(".,:;!?()[]{}")) >= 4
    ]
    search_term = (
        subject_tokens[0]
        if subject_tokens
        else all_payload["emails"][0]["sender"].split("@")[0]
    )

    filtered_response = client.get("/emails", params={"q": search_term, "limit": 10})
    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.json()
    assert filtered_payload["total"] >= 1
    assert all(
        search_term in f"{item['subject']} {item['snippet']} {item['sender']}".lower()
        for item in filtered_payload["emails"]
    )


def test_frontend_recommendations_can_scope_to_one_email():
    recommendations = client.get("/recommendations").json()
    target_email_id = recommendations[0]["emailId"]

    scoped_response = client.get("/recommendations", params={"email_id": target_email_id})

    assert scoped_response.status_code == 200
    scoped_payload = scoped_response.json()
    assert len(scoped_payload) == 1
    assert scoped_payload[0]["emailId"] == target_email_id


def test_frontend_ops_workflows_expose_mailbox_upgrade_features():
    overview_response = client.get("/ops/overview")
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["workflows"]
    assert overview["unreadCount"] >= 1

    scan_response = client.post("/ops/scan", json={"force_refresh": True})
    assert scan_response.status_code == 200
    assert scan_response.json()["runId"]

    auto_label_response = client.post("/ops/auto-label", json={"force_refresh": True})
    assert auto_label_response.status_code == 200
    assert auto_label_response.json()["count"] >= 1
    assert auto_label_response.json()["overview"]["provider"] == overview["provider"]

    safe_cleanup_response = client.post("/ops/safe-cleanup", json={"force_refresh": True})
    assert safe_cleanup_response.status_code == 200
    assert safe_cleanup_response.json()["overview"]["safeCleanupCount"] >= 0

    full_anchor_response = client.post("/ops/full-anchor", json={"force_refresh": True})
    assert full_anchor_response.status_code == 200
    payload = full_anchor_response.json()
    assert payload["labelsApplied"] >= 0
    assert payload["cleanupApplied"] >= 0
    assert payload["overview"]["provider"] == overview["provider"]

    progress_response = client.get("/ops/progress")
    assert progress_response.status_code == 200
    progress_payload = progress_response.json()
    assert {"labeled_count", "archived_count", "marked_read_count", "reply_sent_count"} <= set(
        progress_payload.keys()
    )


def test_frontend_clean_labels_removes_inboxanchor_labels_only():
    auto_label_response = client.post("/ops/auto-label", json={"force_refresh": True})
    assert auto_label_response.status_code == 200
    assert auto_label_response.json()["count"] >= 1

    emails_after_label = client.get("/emails").json()["emails"]
    generated_labels_before = {
        email["id"]: [
            label
            for label in email["labels"]
            if "/" in label or label.startswith("priority/")
        ]
        for email in emails_after_label
    }
    assert any(labels for labels in generated_labels_before.values())

    cleanup_response = client.post("/ops/clean-labels", json={"force_refresh": True})
    assert cleanup_response.status_code == 200
    assert cleanup_response.json()["count"] >= 1
    assert cleanup_response.json()["deletedLabelCount"] >= 1
    assert cleanup_response.json()["deletedLabels"]

    emails_after_cleanup = client.get("/emails").json()["emails"]
    generated_labels_after = {
        email["id"]: [
            label
            for label in email["labels"]
            if "/" in label or label.startswith("priority/")
        ]
        for email in emails_after_cleanup
    }
    assert sum(len(labels) for labels in generated_labels_after.values()) < sum(
        len(labels) for labels in generated_labels_before.values()
    )


def test_frontend_clean_labels_uses_fast_gmail_delete_path_without_rescan(monkeypatch):
    from inboxanchor.api.v1.routers import frontend as frontend_router

    ensure_calls: list[tuple[str | None, bool, str | None]] = []
    delete_calls: list[list[str]] = []

    def fake_ensure_frontend_run(*, provider=None, force=False, time_range=None):
        ensure_calls.append((provider, force, time_range))
        return "gmail-run-1", "gmail"

    monkeypatch.setattr(frontend_router, "_ensure_frontend_run", fake_ensure_frontend_run)
    monkeypatch.setattr(
        frontend_router,
        "_load_email_details",
        lambda run_id: [
            {
                "email_id": "msg-1",
                "subject": "LinkedIn Jobs",
                "labels": ["jobs/alert", "priority/high"],
                "classification": {"confidence": 0.96},
            }
        ],
    )
    monkeypatch.setattr(
        frontend_router,
        "_labels_to_remove_for_email",
        lambda detail: ["jobs/alert", "priority/high"],
    )
    monkeypatch.setattr(
        frontend_router,
        "_record_label_removal_decision",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        frontend_router,
        "_remove_provider_labels",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Gmail fast cleanup should not unlabel messages one by one.")
        ),
    )
    monkeypatch.setattr(
        frontend_router,
        "_delete_provider_labels",
        lambda provider_name, labels: (
            delete_calls.append(labels)
            or {
                "provider": provider_name,
                "action": "delete_labels",
                "deletedLabels": labels,
                "deletedCount": len(labels),
                "details": "Deleted Gmail labels directly.",
            }
        ),
    )
    monkeypatch.setattr(
        frontend_router,
        "_build_ops_overview",
        lambda provider_name, run_id, time_range=None: {
            "provider": provider_name,
            "runId": run_id,
            "timeRange": "all_time",
            "timeRangeLabel": "All time",
        },
    )

    response = client.post(
        "/ops/clean-labels",
        json={"provider": "gmail", "force_refresh": True, "time_range": "all_time"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["deletedLabelCount"] == 2
    assert payload["deletedLabels"] == ["jobs/alert", "priority/high"]
    assert ensure_calls == [("gmail", False, "all_time")]
    assert delete_calls == [["jobs/alert"], ["priority/high"]]


def test_frontend_ops_backfill_builds_mailbox_memory_cache():
    response = client.post(
        "/ops/backfill",
        json={
            "limit": 50,
            "batch_size": 10,
            "include_body": False,
            "unread_only": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 1
    assert payload["cachedCount"] >= payload["count"]
    assert payload["processedTotal"] >= payload["count"]
    assert payload["overview"]["cachedEmailsCount"] >= payload["count"]
    assert "mailboxMemory" in payload["overview"]


def test_frontend_reply_send_works_for_supported_provider():
    signup = client.post(
        "/auth/signup",
        json={
            "full_name": "Reply Operator",
            "email": "reply@example.com",
            "password": "reply-secret-pass",
        },
    )
    token = signup.json()["token"]
    first_email = client.get("/emails").json()["emails"][0]

    response = client.post(
        f"/emails/{first_email['id']}/reply",
        headers={"Authorization": f"Bearer {token}"},
        json={"body": "Thanks, I reviewed this and will get back to you today."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "fake"
    assert payload["toAddress"]


def test_frontend_gmail_aliases_can_be_generated_and_revoked():
    from inboxanchor.api.v1.routers import frontend as frontend_router

    frontend_router.SETTINGS.alias_allow_plus_fallback = True
    configured: list[tuple[str, str, str]] = []
    removed: list[str] = []

    def fake_configure(alias_address: str, *, label: str = "", purpose: str = "") -> str:
        configured.append((alias_address, label, purpose))
        return "InboxAnchor/Aliases/Travel"

    def fake_remove(alias_address: str) -> None:
        removed.append(alias_address)

    original_configure = frontend_router._configure_alias_inbox_routing
    original_remove = frontend_router._remove_alias_inbox_routing
    frontend_router._configure_alias_inbox_routing = fake_configure
    frontend_router._remove_alias_inbox_routing = fake_remove
    try:
        signup = client.post(
            "/auth/signup",
            json={
                "full_name": "Alias Operator",
                "email": "alias-owner@example.com",
                "password": "alias-secret-pass",
            },
        )
        token = signup.json()["token"]
        client.put(
            "/providers/gmail/connection",
            json={
                "status": "connected",
                "account_hint": "owner@gmail.com",
                "sync_enabled": True,
                "dry_run_only": False,
                "notes": "Connected for alias generation tests.",
            },
        )

        generated = client.post(
            "/aliases/generate",
            headers={"Authorization": f"Bearer {token}"},
            json={"label": "travel", "purpose": "airlines"},
        )
        assert generated.status_code == 200
        generated_payload = generated.json()
        assert "+ia-travel" in generated_payload["alias_address"]
        assert generated_payload["status"] == "active"
        assert "InboxAnchor/Aliases/Travel" in generated_payload["note"]
        assert configured == [(generated_payload["alias_address"], "travel", "airlines")]

        listed = client.get("/aliases", headers={"Authorization": f"Bearer {token}"})
        assert listed.status_code == 200
        assert listed.json()["count"] == 1
        assert configured[-1] == (generated_payload["alias_address"], "travel", "airlines")
        assert len(configured) == 2

        revoked = client.post(
            f"/aliases/{generated_payload['id']}/revoke",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert revoked.status_code == 200
        assert revoked.json()["status"] == "revoked"
        assert removed == [generated_payload["alias_address"]]
    finally:
        frontend_router._configure_alias_inbox_routing = original_configure
        frontend_router._remove_alias_inbox_routing = original_remove
        frontend_router.SETTINGS.alias_allow_plus_fallback = False


def test_frontend_alias_generation_requires_managed_domain_when_fallback_disabled():
    from inboxanchor.api.v1.routers import frontend as frontend_router

    frontend_router.SETTINGS.alias_managed_enabled = False
    frontend_router.SETTINGS.alias_domain = ""
    frontend_router.SETTINGS.alias_allow_plus_fallback = False

    signup = client.post(
        "/auth/signup",
        json={
            "full_name": "Strict Alias Operator",
            "email": "strict-owner@example.com",
            "password": "strict-alias-pass",
        },
    )
    token = signup.json()["token"]

    generated = client.post(
        "/aliases/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "travel", "purpose": "airlines"},
    )

    assert generated.status_code == 400
    assert "Managed aliases like" in generated.json()["detail"]


def test_frontend_managed_aliases_use_clean_domain(monkeypatch):
    from inboxanchor.api.v1.routers import frontend as frontend_router

    monkeypatch.setattr(frontend_router.SETTINGS, "alias_managed_enabled", True)
    monkeypatch.setattr(frontend_router.SETTINGS, "alias_domain", "inboxanchor.com")

    signup = client.post(
        "/auth/signup",
        json={
            "full_name": "Managed Alias Operator",
            "email": "managed-owner@example.com",
            "password": "managed-alias-pass",
        },
    )
    token = signup.json()["token"]

    generated = client.post(
        "/aliases/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "travel", "purpose": "airlines"},
    )
    assert generated.status_code == 200
    generated_payload = generated.json()
    assert generated_payload["alias_type"] == "managed"
    assert generated_payload["provider"] == "inboxanchor"
    assert generated_payload["alias_address"].startswith("travel")
    assert generated_payload["alias_address"].endswith("@inboxanchor.com")
    assert "InboxAnchor-managed privacy alias" in generated_payload["note"]

    listed = client.get("/aliases", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["mode"] == "managed"
    assert listed_payload["managed_enabled"] is True
    assert listed_payload["domain"] == "inboxanchor.com"


def test_frontend_alias_resolve_returns_forwarding_payload(monkeypatch):
    from inboxanchor.api.v1.routers import frontend as frontend_router

    monkeypatch.setattr(frontend_router.SETTINGS, "alias_managed_enabled", True)
    monkeypatch.setattr(frontend_router.SETTINGS, "alias_domain", "inboxanchor.com")
    monkeypatch.setattr(
        frontend_router.SETTINGS,
        "alias_resolver_secret",
        "resolver-secret",
    )

    signup = client.post(
        "/auth/signup",
        json={
            "full_name": "Resolver Operator",
            "email": "resolver-owner@example.com",
            "password": "resolver-pass",
        },
    )
    token = signup.json()["token"]

    generated = client.post(
        "/aliases/generate",
        headers={"Authorization": f"Bearer {token}"},
        json={"label": "travel", "purpose": "airlines"},
    )
    alias_address = generated.json()["alias_address"]

    resolved = client.post(
        "/aliases/resolve",
        headers={"X-InboxAnchor-Alias-Secret": "resolver-secret"},
        json={
            "alias_address": alias_address,
            "sender": "alerts@airline.example",
            "subject": "Boarding pass",
        },
    )

    assert resolved.status_code == 200
    payload = resolved.json()
    assert payload["active"] is True
    assert payload["action"] == "forward"
    assert payload["alias_address"] == alias_address
    assert payload["forward_to"] == "resolver-owner@example.com"
    assert payload["skip_inbox"] is True
    assert payload["label_name"] == "InboxAnchor/Aliases/Travel"


def test_frontend_alias_resolve_rejects_unknown_alias(monkeypatch):
    from inboxanchor.api.v1.routers import frontend as frontend_router

    monkeypatch.setattr(
        frontend_router.SETTINGS,
        "alias_resolver_secret",
        "resolver-secret",
    )

    resolved = client.post(
        "/aliases/resolve",
        headers={"X-InboxAnchor-Alias-Secret": "resolver-secret"},
        json={"alias_address": "missing@inboxanchor.com"},
    )

    assert resolved.status_code == 200
    payload = resolved.json()
    assert payload["active"] is False
    assert payload["action"] == "reject"
    assert payload["reason"] == "Alias not found."


def test_frontend_ops_backfill_can_resume_from_saved_offset(monkeypatch):
    seed = build_demo_emails()
    emails = [
        seed[index % len(seed)].model_copy(
            update={
                "id": f"resume-{index}",
                "thread_id": f"thread-resume-{index}",
                "subject": f"Resume subject {index}",
            }
        )
        for index in range(40)
    ]
    calls: list[dict] = []

    class ResumeProvider:
        def iter_mailbox_batches(
            self,
            *,
            limit: int = 500,
            batch_size: int = 100,
            include_body: bool = False,
            unread_only: bool = False,
            offset: int = 0,
            time_range: Optional[str] = None,
        ):
            calls.append(
                {
                    "limit": limit,
                    "batch_size": batch_size,
                    "include_body": include_body,
                    "unread_only": unread_only,
                    "offset": offset,
                    "time_range": time_range,
                }
            )
            selected = emails[offset : offset + limit]
            for start in range(0, len(selected), batch_size):
                yield [item.model_copy(deep=True) for item in selected[start : start + batch_size]]

    monkeypatch.setattr(
        frontend_router,
        "_service_for_provider",
        lambda provider_name: SimpleNamespace(provider=ResumeProvider()),
    )
    monkeypatch.setattr(
        frontend_router,
        "_get_cached_or_latest_run_id",
        lambda provider_name, **kwargs: "resume-run",
    )
    monkeypatch.setattr(
        frontend_router,
        "_build_ops_overview",
        lambda provider_name, run_id, **kwargs: {
            "provider": provider_name,
            "runId": run_id,
            "cachedEmailsCount": 6,
            "mailboxMemory": {
                "resumeOffset": 6,
                "processedTotal": 6,
                "remainingCount": 0,
            },
        },
    )

    first = client.post(
        "/ops/backfill",
        json={"provider": "gmail", "limit": 25, "batch_size": 10, "time_range": "last_1_year"},
    )
    second = client.post(
        "/ops/backfill",
        json={"provider": "gmail", "limit": 40, "batch_size": 10, "time_range": "last_1_year"},
    )
    third = client.post(
        "/ops/backfill",
        json={"provider": "gmail", "limit": 25, "batch_size": 10, "time_range": "last_month"},
    )
    progress = client.get(
        "/ops/progress",
        params={"provider": "gmail", "time_range": "last_1_year"},
    )

    assert first.status_code == 200
    assert first.json()["processedTotal"] == 25
    assert second.status_code == 200
    assert second.json()["count"] == 15
    assert second.json()["processedTotal"] == 40
    assert second.json()["resumeOffset"] == 40
    assert third.status_code == 200
    assert third.json()["resumeOffset"] == 25
    assert calls[0]["offset"] == 0
    assert calls[1]["offset"] == 25
    assert calls[2]["offset"] == 0
    assert calls[0]["time_range"] == "last_1_year"
    assert calls[2]["time_range"] == "last_month"
    assert progress.status_code == 200
    assert progress.json()["resume_offset"] == 40
    assert progress.json()["completed"] is True


def test_frontend_ops_overview_returns_selected_time_range():
    response = client.get("/ops/overview", params={"time_range": "last_6_months"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["timeRange"] == "last_6_months"
    assert payload["timeRangeLabel"] == "Last 6 months"


def test_frontend_ops_overview_surfaces_live_provider_fetch_failure(monkeypatch):
    frontend_router.FRONTEND_RUN_CACHE.clear()
    frontend_router.FRONTEND_SERVICE_CACHE.clear()
    frontend_router.FRONTEND_BLOCK_REGISTRY.clear()
    frontend_router.FRONTEND_FORCE_REFRESH_PROVIDERS.clear()
    frontend_router.FRONTEND_PROVIDER_ERRORS.clear()

    class FailingEngine:
        def run(self, **kwargs):
            raise RuntimeError("Unable to find the server at gmail.googleapis.com")

    class FailingService:
        def __init__(self):
            self.engine = FailingEngine()

        def load_provider_connection(self, provider_name):
            return SimpleNamespace(sync_enabled=True)

    monkeypatch.setattr(
        frontend_router,
        "_service_for_provider",
        lambda provider_name: FailingService(),
    )

    response = client.get("/ops/overview", params={"provider": "gmail"})

    assert response.status_code == 502
    assert "could not reach gmail.googleapis.com" in response.json()["detail"]


def test_frontend_initial_live_run_bootstraps_with_smaller_limit(monkeypatch):
    frontend_router.FRONTEND_RUN_CACHE.clear()
    frontend_router.FRONTEND_SERVICE_CACHE.clear()
    frontend_router.FRONTEND_BLOCK_REGISTRY.clear()
    frontend_router.FRONTEND_FORCE_REFRESH_PROVIDERS.clear()
    frontend_router.FRONTEND_PROVIDER_ERRORS.clear()

    captured: dict[str, int] = {}

    class BootEngine:
        def run(self, **kwargs):
            captured.update(
                {
                    "limit": kwargs["limit"],
                    "batch_size": kwargs["batch_size"],
                    "email_preview_limit": kwargs["email_preview_limit"],
                    "recommendation_preview_limit": kwargs["recommendation_preview_limit"],
                }
            )
            return SimpleNamespace(run_id="boot-gmail-run")

    class BootService:
        def __init__(self):
            self.engine = BootEngine()

    monkeypatch.setattr(
        frontend_router,
        "_service_for_provider",
        lambda provider_name: BootService(),
    )

    run_id, provider_name = frontend_router._ensure_frontend_run(provider="gmail")

    assert run_id == "boot-gmail-run"
    assert provider_name == "gmail"
    assert captured["limit"] == 50
    assert captured["batch_size"] == 50
    assert captured["email_preview_limit"] <= 80
    assert captured["recommendation_preview_limit"] <= 120


def test_frontend_ops_progress_reflects_registry_state():
    frontend_router.FRONTEND_PROGRESS["gmail::all_time"] = {
        "provider": "gmail",
        "time_range": "all_time",
        "time_range_label": "All time",
        "status": "running",
        "stage": "triaging",
        "target_count": 50,
        "processed_count": 12,
        "read_count": 16,
        "action_item_count": 4,
        "recommendation_count": 7,
        "batch_count": 1,
        "latest_subject": "Quarterly budget review",
        "run_id": None,
        "error": None,
        "updated_at": "2026-05-08T19:30:00Z",
    }

    response = client.get("/ops/progress", params={"provider": "gmail"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["processed_count"] == 12
    assert payload["read_count"] == 16
    assert payload["latest_subject"] == "Quarterly budget review"


def test_frontend_ops_progress_reconciles_empty_stale_scan(monkeypatch):
    frontend_router.FRONTEND_PROGRESS["gmail::all_time"] = {
        "provider": "gmail",
        "time_range": "all_time",
        "time_range_label": "All time",
        "mode": "scan",
        "status": "running",
        "stage": "starting",
        "target_count": 10000,
        "processed_count": 0,
        "read_count": 0,
        "action_item_count": 0,
        "recommendation_count": 0,
        "batch_count": 0,
        "cached_count": 0,
        "hydrated_count": 0,
        "labeled_count": 0,
        "labels_removed_count": 0,
        "archived_count": 0,
        "marked_read_count": 0,
        "trashed_count": 0,
        "reply_sent_count": 0,
        "latest_subject": None,
        "latest_action": None,
        "run_id": None,
        "error": None,
        "updated_at": "2026-05-09T08:00:00Z",
    }
    frontend_router.FRONTEND_ACTIVE_RUNS.clear()
    monkeypatch.setattr(
        frontend_router,
        "_get_cached_or_latest_run_id",
        lambda provider_name, time_range=None: "live-run-123",
    )
    monkeypatch.setattr(
        frontend_router,
        "_build_ops_overview",
        lambda provider_name, run_id, time_range=None: {
            "provider": provider_name,
            "timeRange": "all_time",
            "timeRangeLabel": "All time",
            "unreadCount": 245,
            "safeCleanupCount": 18,
            "needsApprovalCount": 7,
            "blockedCount": 3,
            "cachedEmailsCount": 612,
            "hydratedEmailsCount": 401,
            "oldestCachedAt": "2026-05-01T10:00:00Z",
            "newestCachedAt": "2026-05-09T10:00:00Z",
        },
    )

    response = client.get("/ops/progress", params={"provider": "gmail"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["stage"] == "ready"
    assert payload["run_id"] == "live-run-123"
    assert payload["processed_count"] == 245
    assert payload["read_count"] == 245
    assert payload["recommendation_count"] == 28
    assert payload["cached_count"] == 612
    assert payload["hydrated_count"] == 401


def test_frontend_ensure_run_reuses_inflight_provider_job(monkeypatch):
    frontend_router.FRONTEND_RUN_CACHE.clear()
    frontend_router.FRONTEND_SERVICE_CACHE.clear()
    frontend_router.FRONTEND_BLOCK_REGISTRY.clear()
    frontend_router.FRONTEND_FORCE_REFRESH_PROVIDERS.clear()
    frontend_router.FRONTEND_PROVIDER_ERRORS.clear()
    frontend_router.FRONTEND_PROGRESS.clear()
    frontend_router.FRONTEND_ACTIVE_RUNS.clear()

    counts = {"runs": 0}

    class SharedEngine:
        def run(self, **kwargs):
            counts["runs"] += 1
            callback = kwargs.get("progress_callback")
            if callback:
                callback(
                    {
                        "stage": "triaging",
                        "limit": kwargs["limit"],
                        "processed_emails": 5,
                        "read_count": 5,
                        "action_item_count": 2,
                        "recommendation_count": 5,
                        "batch_count": 1,
                    }
                )
            time.sleep(0.15)
            return SimpleNamespace(
                run_id="shared-gmail-run",
                scanned_emails=5,
                total_emails=5,
                action_items={"email-1": []},
                recommendations=[1, 2, 3, 4, 5],
                batch_count=1,
            )

    class SharedService:
        def __init__(self):
            self.engine = SharedEngine()

    monkeypatch.setattr(
        frontend_router,
        "_service_for_provider",
        lambda provider_name: SharedService(),
    )

    results: list[tuple[str, str]] = []

    def worker():
        results.append(frontend_router._ensure_frontend_run(provider="gmail"))

    thread_one = threading.Thread(target=worker)
    thread_two = threading.Thread(target=worker)
    thread_one.start()
    thread_two.start()
    thread_one.join(timeout=2)
    thread_two.join(timeout=2)

    assert counts["runs"] == 1
    assert results == [("shared-gmail-run", "gmail"), ("shared-gmail-run", "gmail")]


def test_frontend_zero_live_run_triggers_fresh_refresh(monkeypatch):
    frontend_router.FRONTEND_RUN_CACHE.clear()
    frontend_router.FRONTEND_SERVICE_CACHE.clear()
    frontend_router.FRONTEND_BLOCK_REGISTRY.clear()
    frontend_router.FRONTEND_FORCE_REFRESH_PROVIDERS.clear()
    frontend_router.FRONTEND_PROVIDER_ERRORS.clear()
    frontend_router.FRONTEND_PROGRESS.clear()
    frontend_router.FRONTEND_ACTIVE_RUNS.clear()

    class ZeroRunRepository:
        def __init__(self, session):
            self.session = session

        def get_run(self, run_id):
            return {"run_id": run_id}

        def get_latest_run_id(self, provider_name):
            assert provider_name == "gmail"
            return "zero-run"

        def count_run_email_details(self, run_id, **kwargs):
            del kwargs
            assert run_id == "zero-run"
            return 0

    class ProbeProvider:
        provider_name = "gmail"

        def list_unread(self, limit=50, include_body=True, time_range=None):
            del limit, include_body, time_range
            return [SimpleNamespace(id="msg-live")]

    class RefreshEngine:
        def run(self, **kwargs):
            return SimpleNamespace(
                run_id="fresh-live-run",
                scanned_emails=1,
                total_emails=1,
                action_items={},
                recommendations=[],
                batch_count=1,
            )

    class RefreshService:
        def __init__(self):
            self.provider = ProbeProvider()
            self.engine = RefreshEngine()

        def load_provider_connection(self, provider_name):
            return SimpleNamespace(
                provider=provider_name,
                status="connected",
                sync_enabled=True,
            )

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(frontend_router, "InboxRepository", ZeroRunRepository)
    monkeypatch.setattr(frontend_router, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        frontend_router,
        "_service_for_provider",
        lambda provider_name: RefreshService(),
    )

    run_id, provider_name = frontend_router._ensure_frontend_run(provider="gmail")

    assert run_id == "fresh-live-run"
    assert provider_name == "gmail"


def test_frontend_zero_bounded_run_uses_cached_scope_without_live_probe(monkeypatch):
    frontend_router.FRONTEND_RUN_CACHE.clear()
    frontend_router.FRONTEND_SERVICE_CACHE.clear()
    frontend_router.FRONTEND_BLOCK_REGISTRY.clear()
    frontend_router.FRONTEND_FORCE_REFRESH_PROVIDERS.clear()
    frontend_router.FRONTEND_PROVIDER_ERRORS.clear()
    frontend_router.FRONTEND_PROGRESS.clear()
    frontend_router.FRONTEND_ACTIVE_RUNS.clear()

    scoped_key = frontend_router._scope_key("gmail", "older_than_10_years")
    frontend_router.FRONTEND_RUN_CACHE[scoped_key] = "zero-bounded-run"

    class ZeroBoundedRepository:
        def __init__(self, session):
            self.session = session

        def get_run(self, run_id):
            assert run_id == "zero-bounded-run"
            return {"run_id": run_id}

        def count_run_email_details(self, run_id, **kwargs):
            del kwargs
            assert run_id == "zero-bounded-run"
            return 0

    class NoProbeProvider:
        provider_name = "gmail"

        def list_unread(self, *args, **kwargs):
            raise AssertionError("Historical zero runs should not probe Gmail again.")

    class ConnectedService:
        def __init__(self):
            self.provider = NoProbeProvider()

        def load_provider_connection(self, provider_name):
            return SimpleNamespace(
                provider=provider_name,
                status="connected",
                sync_enabled=True,
            )

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(frontend_router, "InboxRepository", ZeroBoundedRepository)
    monkeypatch.setattr(frontend_router, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        frontend_router,
        "_service_for_provider",
        lambda provider_name: ConnectedService(),
    )

    run_id, provider_name = frontend_router._ensure_frontend_run(
        provider="gmail",
        time_range="older_than_10_years",
    )

    assert run_id == "zero-bounded-run"
    assert provider_name == "gmail"


def test_frontend_gmail_auth_routes_issue_local_session(monkeypatch, tmp_path):
    credentials_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"
    credentials_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(auth_router.SETTINGS, "gmail_credentials_path", str(credentials_path))
    monkeypatch.setattr(auth_router.SETTINGS, "gmail_token_path", str(token_path))
    monkeypatch.setattr(
        auth_router.SETTINGS,
        "gmail_redirect_uri",
        "http://localhost:3000/login",
    )
    monkeypatch.setattr(
        auth_router,
        "build_authorization_url",
        lambda *args, **kwargs: (
            "https://accounts.google.com/o/oauth2/test",
            "state-123",
            "frontend-verifier",
        ),
    )
    callback_payload: dict[str, str | None] = {}
    monkeypatch.setattr(
        auth_router,
        "exchange_code_for_token",
        lambda *args, **kwargs: callback_payload.update(
            {"state": kwargs.get("state"), "code_verifier": kwargs.get("code_verifier")}
        )
        or object(),
    )
    monkeypatch.setattr(
        auth_router,
        "_fetch_google_email",
        lambda credentials: "gmail.user@example.com",
    )
    marked_providers: list[str] = []
    monkeypatch.setattr(
        auth_router,
        "mark_frontend_provider_dirty",
        lambda provider_name: marked_providers.append(provider_name),
    )

    auth_url_response = client.get(
        "/auth/gmail/url",
        headers={"Referer": "http://localhost:3000/login"},
    )
    assert auth_url_response.status_code == 200
    assert auth_url_response.json()["auth_url"].startswith("https://accounts.google.com/")

    callback_response = client.post(
        "/auth/gmail/callback",
        json={"code": "demo-code", "state": "state-123"},
        headers={"Referer": "http://localhost:3000/login?code=demo-code"},
    )
    assert callback_response.status_code == 200
    payload = callback_response.json()
    assert payload["email"] == "gmail.user@example.com"
    assert payload["access_token"]

    me_response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["authenticated"] is True
    assert me_response.json()["user"]["email"] == "gmail.user@example.com"

    connection_response = client.get("/providers/gmail/connection")
    assert connection_response.status_code == 200
    assert connection_response.json()["status"] == "connected"
    workspace_response = client.get("/settings/workspace")
    assert workspace_response.status_code == 200
    assert workspace_response.json()["preferred_provider"] == "gmail"
    assert callback_payload["state"] == "state-123"
    assert callback_payload["code_verifier"] == "frontend-verifier"
    assert marked_providers == ["gmail"]


def test_frontend_gmail_auth_always_uses_login_redirect(monkeypatch, tmp_path):
    credentials_path = tmp_path / "credentials.json"
    token_path = tmp_path / "token.json"
    credentials_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(auth_router.SETTINGS, "gmail_credentials_path", str(credentials_path))
    monkeypatch.setattr(auth_router.SETTINGS, "gmail_token_path", str(token_path))

    captured: dict[str, str] = {}

    def fake_build_authorization_url(*args, **kwargs):
        captured["redirect_uri"] = kwargs["redirect_uri"]
        return "https://accounts.google.com/o/oauth2/test", "state-123", "frontend-verifier"

    monkeypatch.setattr(auth_router, "build_authorization_url", fake_build_authorization_url)

    response = client.get(
        "/auth/gmail/url",
        headers={"Referer": "http://localhost:8080/settings"},
    )

    assert response.status_code == 200
    assert captured["redirect_uri"] == "http://localhost:8080/login"
