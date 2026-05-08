from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from inboxanchor.bootstrap import InboxAnchorService, list_provider_profiles
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.models import ProviderConnectionState, WorkspacePolicy, WorkspaceSettings

APPROVAL_REGISTRY: dict[str, set[str]] = {}


class TriageRunRequest(BaseModel):
    provider: Optional[str] = None
    dry_run: Optional[bool] = None
    limit: Optional[int] = Field(default=None, ge=1, le=10000)
    batch_size: Optional[int] = Field(default=None, ge=25, le=1000)
    email_preview_limit: Optional[int] = Field(default=None, ge=10, le=500)
    recommendation_preview_limit: Optional[int] = Field(default=None, ge=10, le=1000)
    category_filters: list[str] = Field(default_factory=list)
    confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ApprovalRequest(BaseModel):
    run_id: str
    email_ids: list[str]


class ExecuteRequest(BaseModel):
    run_id: str
    explicit_trash_confirmation: bool = False


class WorkspaceSettingsRequest(BaseModel):
    preferred_provider: str = "fake"
    dry_run_default: bool = True
    default_scan_limit: int = Field(default=500, ge=25, le=10000)
    default_batch_size: int = Field(default=250, ge=25, le=1000)
    default_confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    default_email_preview_limit: int = Field(default=120, ge=10, le=500)
    default_recommendation_preview_limit: int = Field(default=180, ge=10, le=1000)
    onboarding_completed: bool = False
    operator_mode: str = "safe"
    policy: WorkspacePolicy = Field(default_factory=WorkspacePolicy)


class ProviderConnectionRequest(BaseModel):
    status: str = "not_connected"
    account_hint: str = ""
    sync_enabled: bool = False
    dry_run_only: bool = True
    notes: str = ""


@lru_cache
def get_service() -> InboxAnchorService:
    return InboxAnchorService()


app = FastAPI(title="InboxAnchor", version="0.1.0")


@app.get("/health")
def health():
    service = get_service()
    return {"status": "ok", "provider": service.provider.provider_name}


@app.get("/emails/unread")
def unread_emails(limit: int = 25):
    service = get_service()
    emails = service.provider.list_unread(limit=limit, include_body=True)
    return {"count": len(emails), "items": [email.model_dump(mode="json") for email in emails]}


@app.get("/providers")
def list_providers():
    service = get_service()
    items = []
    for profile in list_provider_profiles():
        connection = service.load_provider_connection(profile.slug)
        payload = profile.model_dump(mode="json")
        payload["connection"] = connection.model_dump(mode="json")
        items.append(payload)
    return {"count": len(items), "items": items}


@app.get("/settings/workspace")
def get_workspace_settings():
    service = get_service()
    return service.load_workspace_settings().model_dump(mode="json")


@app.put("/settings/workspace")
def save_workspace_settings(payload: WorkspaceSettingsRequest):
    service = get_service()
    settings = WorkspaceSettings.model_validate(payload.model_dump())
    saved = service.save_workspace_settings(settings)
    return saved.model_dump(mode="json")


@app.get("/providers/{provider}/connection")
def get_provider_connection(provider: str):
    service = get_service()
    return service.load_provider_connection(provider).model_dump(mode="json")


@app.put("/providers/{provider}/connection")
def save_provider_connection(provider: str, payload: ProviderConnectionRequest):
    service = get_service()
    state = ProviderConnectionState(
        provider=provider,
        last_tested_at=datetime.now(timezone.utc),
        **payload.model_dump(),
    )
    saved = service.save_provider_connection(state)
    return saved.model_dump(mode="json")


@app.post("/triage/run")
def run_triage(payload: TriageRunRequest):
    default_service = get_service()
    settings = default_service.load_workspace_settings()
    provider_name = payload.provider or settings.preferred_provider
    service = InboxAnchorService(provider_name=provider_name)
    result = service.engine.run(
        dry_run=settings.dry_run_default if payload.dry_run is None else payload.dry_run,
        limit=settings.default_scan_limit if payload.limit is None else payload.limit,
        batch_size=(
            settings.default_batch_size
            if payload.batch_size is None
            else payload.batch_size
        ),
        category_filters=payload.category_filters or None,
        confidence_threshold=(
            settings.default_confidence_threshold
            if payload.confidence_threshold is None
            else payload.confidence_threshold
        ),
        email_preview_limit=(
            settings.default_email_preview_limit
            if payload.email_preview_limit is None
            else payload.email_preview_limit
        ),
        recommendation_preview_limit=(
            settings.default_recommendation_preview_limit
            if payload.recommendation_preview_limit is None
            else payload.recommendation_preview_limit
        ),
        workspace_policy=settings.policy,
    )
    return result.model_dump(mode="json")


@app.get("/triage")
def list_triage_runs(limit: int = 25):
    with session_scope() as session:
        items = InboxRepository(session).list_runs(limit=limit)
    return {"count": len(items), "items": items}


@app.get("/triage/{run_id}")
def get_triage_run(run_id: str):
    with session_scope() as session:
        payload = InboxRepository(session).get_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Run not found")
    return payload


@app.get("/triage/{run_id}/emails")
def get_triage_run_emails(run_id: str, limit: int = 50, offset: int = 0):
    with session_scope() as session:
        repository = InboxRepository(session)
        items = repository.list_run_emails(run_id, limit=limit, offset=offset)
        total = repository.count_run_emails(run_id)
    return {"count": len(items), "total": total, "items": items}


@app.get("/triage/{run_id}/email-details")
def get_triage_run_email_details(
    run_id: str,
    limit: int = 50,
    offset: int = 0,
    priority: Optional[str] = None,
    category: Optional[str] = None,
):
    normalized_priority = None if priority in {None, "", "all"} else priority
    normalized_category = None if category in {None, "", "all"} else category
    with session_scope() as session:
        repository = InboxRepository(session)
        items = repository.list_run_email_details(
            run_id,
            limit=limit,
            offset=offset,
            priority=normalized_priority,
            category=normalized_category,
        )
        total = repository.count_run_email_details(
            run_id,
            priority=normalized_priority,
            category=normalized_category,
        )
    return {"count": len(items), "total": total, "items": items}


@app.get("/triage/{run_id}/recommendations")
def get_triage_run_recommendations(
    run_id: str,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
):
    with session_scope() as session:
        repository = InboxRepository(session)
        items = repository.list_run_recommendations(
            run_id,
            limit=limit,
            offset=offset,
            status=status,
        )
        total = repository.count_run_recommendations(run_id, status=status)
    return {"count": len(items), "total": total, "items": items}


@app.get("/triage/{run_id}/recommendation-details")
def get_triage_run_recommendation_details(
    run_id: str,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
):
    normalized_status = None if status in {None, "", "all"} else status
    with session_scope() as session:
        repository = InboxRepository(session)
        items = repository.list_run_recommendation_details(
            run_id,
            limit=limit,
            offset=offset,
            status=normalized_status,
        )
        total = repository.count_run_recommendations(run_id, status=normalized_status)
    return {"count": len(items), "total": total, "items": items}


@app.post("/actions/approve")
def approve_actions(payload: ApprovalRequest):
    approved = APPROVAL_REGISTRY.setdefault(payload.run_id, set())
    approved.update(payload.email_ids)
    return {"run_id": payload.run_id, "approved_email_ids": sorted(approved)}


@app.post("/actions/reject")
def reject_actions(payload: ApprovalRequest):
    approved = APPROVAL_REGISTRY.setdefault(payload.run_id, set())
    for email_id in payload.email_ids:
        approved.discard(email_id)
    return {"run_id": payload.run_id, "approved_email_ids": sorted(approved)}


@app.post("/actions/execute")
def execute_actions(payload: ExecuteRequest):
    approved_email_ids = sorted(APPROVAL_REGISTRY.get(payload.run_id, set()))
    if not approved_email_ids:
        return {"run_id": payload.run_id, "executed": []}
    with session_scope() as session:
        repository = InboxRepository(session)
        stored = repository.get_run(payload.run_id)
        if not stored:
            raise HTTPException(status_code=404, detail="Run not found")
        run_result = repository.build_execution_result(payload.run_id, approved_email_ids)
    execution_service = InboxAnchorService(provider_name=stored.get("provider"))
    decisions = execution_service.engine.execute_actions(
        run_result,
        approved_email_ids=approved_email_ids,
        explicit_trash_confirmation=payload.explicit_trash_confirmation,
    )
    return {
        "run_id": payload.run_id,
        "executed": [decision.model_dump(mode="json") for decision in decisions],
    }


@app.get("/audit")
def list_audit():
    with session_scope() as session:
        entries = InboxRepository(session).list_audit_entries()
    return {"count": len(entries), "items": [entry.model_dump(mode="json") for entry in entries]}
