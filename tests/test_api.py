from typing import Optional

from fastapi.testclient import TestClient

import inboxanchor.api.main as api_main
from inboxanchor.api.main import app

client = TestClient(app)


def test_api_health():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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
