import base64
import json
from typing import Optional

from fastapi.testclient import TestClient

import inboxanchor.api.main as api_main
import inboxanchor.api.v1.routers.auth as auth_router
import inboxanchor.api.v1.routers.oauth as oauth_router
from inboxanchor.api.main import app

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
        if rec["recommended_action"] == "archive"
        and rec["status"] == "requires_approval"
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
        if rec["recommended_action"] == "archive"
        and rec["status"] == "requires_approval"
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
        lambda *args, **kwargs: ("https://accounts.google.com/test-auth", "state-123"),
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
    monkeypatch.setattr(
        oauth_router,
        "exchange_code_for_token",
        lambda *args, **kwargs: object(),
    )

    response = client.get("/oauth/gmail/callback", params={"code": "demo-code", "state": "demo"})
    connection = client.get("/providers/gmail/connection")

    assert response.status_code == 200
    assert "Gmail connected successfully" in response.text
    assert connection.status_code == 200
    assert connection.json()["status"] == "connected"
    assert connection.json()["sync_enabled"] is True


def test_frontend_compat_endpoints_expose_react_contract():
    emails_response = client.get("/emails")
    classifications_response = client.get("/classifications")
    recommendations_response = client.get("/recommendations")
    digest_response = client.get("/digest")
    webhook_health_response = client.get("/health/webhook")

    assert emails_response.status_code == 200
    emails_payload = emails_response.json()
    assert emails_payload["total"] >= len(emails_payload["emails"]) > 0
    first_email = emails_payload["emails"][0]
    assert {"id", "threadId", "sender", "subject", "receivedAt", "hasAttachments"} <= set(
        first_email.keys()
    )

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
        lambda *args, **kwargs: ("https://accounts.google.com/o/oauth2/test", "state-123"),
    )
    monkeypatch.setattr(
        auth_router,
        "exchange_code_for_token",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        auth_router,
        "_fetch_google_email",
        lambda credentials: "gmail.user@example.com",
    )

    auth_url_response = client.get(
        "/auth/gmail/url",
        headers={"Referer": "http://localhost:3000/login"},
    )
    assert auth_url_response.status_code == 200
    assert auth_url_response.json()["auth_url"].startswith("https://accounts.google.com/")

    callback_response = client.post(
        "/auth/gmail/callback",
        json={"code": "demo-code"},
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
