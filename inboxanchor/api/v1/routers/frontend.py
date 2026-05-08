from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from inboxanchor.bootstrap import InboxAnchorService
from inboxanchor.infra.audit_log import AuditLogger
from inboxanchor.infra.auth import AuthService
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.models import AutomationDecision, SafetyStatus, WorkspaceSettings

router = APIRouter(tags=["frontend-compat"])

FRONTEND_RUN_CACHE: dict[str, str] = {}
FRONTEND_SERVICE_CACHE: dict[str, InboxAnchorService] = {}
FRONTEND_BLOCK_REGISTRY: dict[str, set[str]] = {}


@dataclass
class FrontendStreamHub:
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_event_at: Optional[datetime] = None
    subscribers: list[asyncio.Queue[str]] = field(default_factory=list)

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        if queue in self.subscribers:
            self.subscribers.remove(queue)

    def emit(self, payload: dict) -> None:
        self.last_event_at = datetime.now(timezone.utc)
        message = json.dumps(payload)
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(message)
            except Exception:
                self.unsubscribe(queue)


STREAM_HUB = FrontendStreamHub()


class FrontendRecommendationActionRequest(BaseModel):
    action: str


class FrontendProviderWorkflowRequest(BaseModel):
    provider: Optional[str] = None
    force_refresh: bool = True


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _current_actor_email(authorization: Optional[str]) -> str:
    token = _extract_bearer_token(authorization)
    if not token:
        return "workspace@inboxanchor.local"
    with session_scope() as session:
        auth_session = AuthService(session).get_session(token)
    if auth_session is None:
        return "workspace@inboxanchor.local"
    return auth_session.user.email


def _get_provider_name(provider: Optional[str] = None) -> str:
    service = InboxAnchorService()
    settings = service.load_workspace_settings()
    return (provider or settings.preferred_provider or "fake").lower()


def _get_workspace_settings() -> WorkspaceSettings:
    return InboxAnchorService().load_workspace_settings()


def _service_for_provider(provider_name: str) -> InboxAnchorService:
    service = FRONTEND_SERVICE_CACHE.get(provider_name)
    if service is None:
        service = InboxAnchorService(provider_name=provider_name)
        FRONTEND_SERVICE_CACHE[provider_name] = service
    return service


def _ensure_frontend_run(*, provider: Optional[str] = None, force: bool = False) -> tuple[str, str]:
    provider_name = _get_provider_name(provider)
    service = _service_for_provider(provider_name)
    settings = _get_workspace_settings()

    with session_scope() as session:
        repository = InboxRepository(session)
        if not force:
            cached_run_id = FRONTEND_RUN_CACHE.get(provider_name)
            if cached_run_id and repository.get_run(cached_run_id):
                return cached_run_id, provider_name
            latest_run_id = repository.get_latest_run_id(provider_name)
            if latest_run_id:
                FRONTEND_RUN_CACHE[provider_name] = latest_run_id
                return latest_run_id, provider_name

    result = service.engine.run(
        dry_run=True,
        limit=settings.default_scan_limit,
        batch_size=settings.default_batch_size,
        confidence_threshold=settings.default_confidence_threshold,
        email_preview_limit=max(
            settings.default_email_preview_limit,
            min(settings.default_scan_limit, 500),
        ),
        recommendation_preview_limit=max(
            settings.default_recommendation_preview_limit,
            min(settings.default_scan_limit, 750),
        ),
        workspace_policy=settings.policy,
    )
    FRONTEND_RUN_CACHE[provider_name] = result.run_id
    STREAM_HUB.emit(
        {
            "type": "triage_refreshed",
            "provider": provider_name,
            "run_id": result.run_id,
        }
    )
    return result.run_id, provider_name


def _normalize_label(label: str) -> str:
    return label.strip().replace(" ", "-").lower()


def _dedupe_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for label in labels:
        normalized = _normalize_label(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _frontend_recommendation_payload(detail: dict, *, blocked: bool = False) -> dict:
    classification = detail["classification"]
    category = classification["category"]
    priority = classification["priority"]
    recommended_action = detail["recommended_action"]

    proposed_labels = _dedupe_labels(
        detail.get("proposed_labels", [])
        + ([] if category == "unknown" else [category])
        + ([f"priority-{priority}"] if priority in {"critical", "high"} else [])
        + (
            ["action-needed"]
            if category in {"work", "finance", "opportunity", "urgent"}
            else []
        )
    )

    if recommended_action == "review":
        if priority in {"critical", "high"}:
            recommended_action = "flag_urgent"
        elif proposed_labels:
            recommended_action = "label"
        else:
            recommended_action = "none"

    status = "blocked" if blocked else detail["status"]
    requires_approval = status != "safe"
    reason = detail["reason"]
    if blocked and not reason.lower().startswith("manually blocked"):
        reason = f"Manually blocked by user. {reason}"

    return {
        "emailId": detail["email_id"],
        "recommendedAction": recommended_action,
        "reason": reason,
        "confidence": detail["confidence"],
        "status": status,
        "requiresApproval": requires_approval,
        "proposedLabels": proposed_labels,
    }


def _recommended_labels_for_email(detail: dict) -> list[str]:
    classification = detail["classification"]
    category = classification["category"]
    priority = classification["priority"]
    labels = []
    if category and category != "unknown":
        labels.append(category)
    if priority in {"critical", "high"}:
        labels.append(f"priority-{priority}")
    if detail["has_attachments"]:
        labels.append("has-attachments")
    if category in {"urgent", "work", "finance", "opportunity"}:
        labels.append("needs-action")
    if category in {"newsletter", "promo", "low_priority"}:
        labels.append("cleanup-candidate")
    return _dedupe_labels(labels)


def _frontend_email_payload(detail: dict) -> dict:
    return {
        "id": detail["email_id"],
        "threadId": detail["thread_id"],
        "sender": detail["sender"],
        "subject": detail["subject"],
        "snippet": detail["snippet"],
        "receivedAt": detail["received_at"],
        "labels": detail["labels"],
        "hasAttachments": detail["has_attachments"],
        "unread": detail["unread"],
    }


def _frontend_classification_payload(detail: dict) -> dict:
    classification = detail["classification"]
    return {
        "category": classification["category"],
        "priority": classification["priority"],
        "confidence": classification["confidence"],
        "reason": classification["reason"],
    }


def _load_email_details(run_id: str) -> list[dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        total = repository.count_run_email_details(run_id)
        return repository.list_run_email_details(run_id, limit=max(total, 1), offset=0)


def _load_recommendation_details(run_id: str) -> list[dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        total = repository.count_run_recommendations(run_id)
        return repository.list_run_recommendation_details(run_id, limit=max(total, 1), offset=0)


def _load_digest(run_id: str) -> dict:
    with session_scope() as session:
        payload = InboxRepository(session).get_run(run_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Run not found")
    return payload["digest"]


def _load_action_items(run_id: str, email_id: str) -> list[dict]:
    with session_scope() as session:
        return InboxRepository(session).list_action_items_for_email(run_id, email_id)


def _find_recommendation_detail(run_id: str, email_id: str) -> dict:
    with session_scope() as session:
        detail = InboxRepository(session).get_run_recommendation_detail(run_id, email_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return detail


def _apply_provider_action(
    provider_name: str,
    email_id: str,
    action: str,
    labels: list[str],
    *,
    reason: str,
    confidence: float,
    approved_by_user: bool,
    safety_status: str,
) -> dict:
    service = _service_for_provider(provider_name)
    provider = service.provider
    if labels:
        provider.apply_labels([email_id], labels, dry_run=False)

    final_action = action
    if action == "mark_read":
        provider.batch_mark_as_read([email_id], dry_run=False)
    elif action == "archive":
        provider.archive_emails([email_id], dry_run=False)
    elif action == "trash":
        provider.move_to_trash(
            [email_id],
            explicit_confirmation=True,
            dry_run=False,
        )
    elif action in {"label", "flag_urgent", "none", "review"}:
        final_action = "label" if labels else "reviewed"
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported action '{action}'.")

    decision = AutomationDecision(
        email_id=email_id,
        proposed_action=action,
        final_action=final_action,
        approved_by_user=approved_by_user,
        reason=reason,
        confidence=confidence,
        safety_verifier_status=safety_status,
    )
    audit_logger = AuditLogger()
    audit_entry = audit_logger.create_entry(decision)
    with session_scope() as session:
        InboxRepository(session).add_audit_entry(audit_entry)
    return {
        "emailId": email_id,
        "action": action,
        "finalAction": final_action,
        "labelsApplied": labels,
    }


def _build_ops_overview(provider_name: str, run_id: str) -> dict:
    settings = _get_workspace_settings()
    details = _load_email_details(run_id)
    recommendations = _load_recommendation_details(run_id)
    digest = _load_digest(run_id)
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    connection = InboxAnchorService().load_provider_connection(provider_name)

    safe_count = sum(1 for item in recommendations if item["status"] == "safe")
    review_count = sum(1 for item in recommendations if item["status"] == "requires_approval")
    blocked_count = sum(1 for item in recommendations if item["status"] == "blocked")
    auto_label_candidates = sum(1 for item in details if _recommended_labels_for_email(item))
    high_priority_count = sum(
        1
        for item in details
        if item["classification"]["priority"] in {"critical", "high"}
    )
    attachment_count = sum(1 for item in details if item["has_attachments"])

    return {
        "provider": provider_name,
        "runId": run_id,
        "unreadCount": digest["total_unread"],
        "highPriorityCount": high_priority_count,
        "safeCleanupCount": safe_count,
        "needsApprovalCount": review_count,
        "blockedCount": blocked_count + len(blocked),
        "autoLabelCandidates": auto_label_candidates,
        "attachmentsCount": attachment_count,
        "categoryCounts": digest["category_counts"],
        "summary": digest["summary"],
        "liveConnected": connection.sync_enabled,
        "providerStatus": connection.status,
        "accountHint": connection.account_hint,
        "workflows": [
            {
                "slug": "scan",
                "label": "Fresh unread scan",
                "description": "Rebuild the unread inventory before taking action.",
                "impact": f"Scans up to {settings.default_scan_limit} unread emails.",
            },
            {
                "slug": "auto-label",
                "label": "Auto-label unread mail",
                "description": "Apply category, urgency, attachment, and action labels.",
                "impact": (
                    f"{auto_label_candidates} unread emails can receive helpful "
                    "labels right now."
                ),
            },
            {
                "slug": "safe-cleanup",
                "label": "Run safe cleanup",
                "description": "Apply only low-risk mark-read and archive actions.",
                "impact": f"{safe_count} recommendations are safe to execute immediately.",
            },
            {
                "slug": "full-anchor",
                "label": "Mailbox upgrade sweep",
                "description": "Label first, then run safe cleanup on the same unread set.",
                "impact": (
                    "Best for making Gmail, Yahoo, and IMAP inboxes visibly cleaner "
                    "without unsafe deletion."
                ),
            },
        ],
    }


@router.get("/emails")
def frontend_emails(
    q: str = "",
    category: str = "",
    priority: str = "",
    unread_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    run_id, _ = _ensure_frontend_run()
    items = _load_email_details(run_id)

    normalized_q = q.strip().lower()
    if normalized_q:
        items = [
            item
            for item in items
            if normalized_q in item["subject"].lower()
            or normalized_q in item["sender"].lower()
            or normalized_q in item["snippet"].lower()
        ]
    if category:
        items = [item for item in items if item["classification"]["category"] == category]
    if priority:
        items = [item for item in items if item["classification"]["priority"] == priority]
    if unread_only:
        items = [item for item in items if item["unread"]]

    total = len(items)
    page = items[offset : offset + limit]
    return {"emails": [_frontend_email_payload(item) for item in page], "total": total}


@router.get("/classifications")
def frontend_classifications():
    run_id, _ = _ensure_frontend_run()
    details = _load_email_details(run_id)
    return {
        item["email_id"]: _frontend_classification_payload(item)
        for item in details
    }


@router.get("/recommendations")
def frontend_recommendations():
    run_id, provider_name = _ensure_frontend_run()
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    details = _load_recommendation_details(run_id)
    return [
        _frontend_recommendation_payload(item, blocked=item["email_id"] in blocked)
        for item in details
    ]


@router.get("/emails/{email_id}/actions")
def frontend_action_items(email_id: str):
    run_id, _ = _ensure_frontend_run()
    items = _load_action_items(run_id, email_id)
    return [
        {
            "emailId": item["email_id"],
            "actionType": item["action_type"],
            "description": item["description"],
            "requiresReply": item["requires_reply"],
        }
        for item in items
    ]


@router.get("/digest")
def frontend_digest():
    run_id, _ = _ensure_frontend_run()
    digest = _load_digest(run_id)
    return {
        "totalUnread": digest["total_unread"],
        "categoryCounts": digest["category_counts"],
        "highPriorityIds": digest["high_priority_ids"],
        "summary": digest["summary"],
    }


@router.get("/ops/overview")
def frontend_ops_overview(provider: str = ""):
    run_id, provider_name = _ensure_frontend_run(provider=provider or None)
    return _build_ops_overview(provider_name, run_id)


@router.post("/ops/scan")
def frontend_ops_scan(payload: FrontendProviderWorkflowRequest):
    run_id, provider_name = _ensure_frontend_run(
        provider=payload.provider,
        force=payload.force_refresh,
    )
    overview = _build_ops_overview(provider_name, run_id)
    STREAM_HUB.emit(
        {
            "type": "scan_completed",
            "provider": provider_name,
            "run_id": run_id,
        }
    )
    return overview


@router.post("/ops/auto-label")
def frontend_ops_auto_label(payload: FrontendProviderWorkflowRequest):
    run_id, provider_name = _ensure_frontend_run(provider=payload.provider)
    details = _load_email_details(run_id)
    applied: list[dict] = []
    for detail in details:
        labels = _recommended_labels_for_email(detail)
        if not labels:
            continue
        classification = detail["classification"]
        applied.append(
            _apply_provider_action(
                provider_name,
                detail["email_id"],
                "label",
                labels,
                reason="Applied InboxAnchor organization labels to an unread email.",
                confidence=classification["confidence"],
                approved_by_user=True,
                safety_status=SafetyStatus.allowed,
            )
        )

    refreshed_run_id, _ = _ensure_frontend_run(
        provider=provider_name,
        force=payload.force_refresh,
    )
    overview = _build_ops_overview(provider_name, refreshed_run_id)
    STREAM_HUB.emit(
        {
            "type": "auto_label_completed",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "count": len(applied),
        }
    )
    return {"applied": applied, "count": len(applied), "overview": overview}


@router.post("/ops/safe-cleanup")
def frontend_ops_safe_cleanup(payload: FrontendProviderWorkflowRequest):
    run_id, provider_name = _ensure_frontend_run(provider=payload.provider)
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    details = _load_recommendation_details(run_id)
    applied: list[dict] = []
    for detail in details:
        recommendation = _frontend_recommendation_payload(
            detail,
            blocked=detail["email_id"] in blocked,
        )
        if recommendation["status"] != "safe":
            continue
        applied.append(
            _apply_provider_action(
                provider_name,
                detail["email_id"],
                recommendation["recommendedAction"],
                recommendation["proposedLabels"],
                reason=recommendation["reason"],
                confidence=recommendation["confidence"],
                approved_by_user=True,
                safety_status=SafetyStatus.allowed,
            )
        )

    refreshed_run_id, _ = _ensure_frontend_run(
        provider=provider_name,
        force=payload.force_refresh,
    )
    overview = _build_ops_overview(provider_name, refreshed_run_id)
    STREAM_HUB.emit(
        {
            "type": "safe_cleanup_completed",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "count": len(applied),
        }
    )
    return {"applied": applied, "count": len(applied), "overview": overview}


@router.post("/ops/full-anchor")
def frontend_ops_full_anchor(payload: FrontendProviderWorkflowRequest):
    label_result = frontend_ops_auto_label(
        FrontendProviderWorkflowRequest(
            provider=payload.provider,
            force_refresh=False,
        )
    )
    cleanup_result = frontend_ops_safe_cleanup(
        FrontendProviderWorkflowRequest(
            provider=payload.provider,
            force_refresh=payload.force_refresh,
        )
    )
    return {
        "labelsApplied": label_result["count"],
        "cleanupApplied": cleanup_result["count"],
        "overview": cleanup_result["overview"],
    }


@router.post("/recommendations/apply-all-safe")
def frontend_apply_all_safe(authorization: Optional[str] = Header(default=None)):
    run_id, provider_name = _ensure_frontend_run()
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    details = _load_recommendation_details(run_id)
    applied: list[dict] = []
    for detail in details:
        payload = _frontend_recommendation_payload(detail, blocked=detail["email_id"] in blocked)
        if payload["status"] != "safe":
            continue
        applied.append(
            _apply_provider_action(
                provider_name,
                detail["email_id"],
                payload["recommendedAction"],
                payload["proposedLabels"],
                reason=payload["reason"],
                confidence=payload["confidence"],
                approved_by_user=bool(_extract_bearer_token(authorization)),
                safety_status=SafetyStatus.allowed,
            )
        )
        blocked.discard(detail["email_id"])

    refreshed_run_id, _ = _ensure_frontend_run(provider=provider_name, force=True)
    STREAM_HUB.emit(
        {
            "type": "actions_applied",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "count": len(applied),
        }
    )
    return {"applied": applied, "count": len(applied)}


@router.post("/recommendations/{email_id}/apply")
def frontend_apply_recommendation(
    email_id: str,
    payload: FrontendRecommendationActionRequest,
    authorization: Optional[str] = Header(default=None),
):
    run_id, provider_name = _ensure_frontend_run()
    detail = _find_recommendation_detail(run_id, email_id)
    recommendation = _frontend_recommendation_payload(detail)
    result = _apply_provider_action(
        provider_name,
        email_id,
        payload.action,
        recommendation["proposedLabels"],
        reason=recommendation["reason"],
        confidence=recommendation["confidence"],
        approved_by_user=bool(_extract_bearer_token(authorization)),
        safety_status=SafetyStatus.allowed,
    )
    FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set()).discard(email_id)
    refreshed_run_id, _ = _ensure_frontend_run(provider=provider_name, force=True)
    STREAM_HUB.emit(
        {
            "type": "recommendation_applied",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "email_id": email_id,
        }
    )
    return {"ok": True, **result}


@router.post("/recommendations/{email_id}/approve")
def frontend_approve_recommendation(
    email_id: str,
    payload: FrontendRecommendationActionRequest,
    authorization: Optional[str] = Header(default=None),
):
    run_id, provider_name = _ensure_frontend_run()
    detail = _find_recommendation_detail(run_id, email_id)
    recommendation = _frontend_recommendation_payload(detail)
    result = _apply_provider_action(
        provider_name,
        email_id,
        payload.action,
        recommendation["proposedLabels"],
        reason=recommendation["reason"],
        confidence=recommendation["confidence"],
        approved_by_user=True,
        safety_status=SafetyStatus.requires_review,
    )
    FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set()).discard(email_id)
    actor_email = _current_actor_email(authorization)
    STREAM_HUB.emit(
        {
            "type": "recommendation_approved",
            "provider": provider_name,
            "email_id": email_id,
            "actor": actor_email,
        }
    )
    _ensure_frontend_run(provider=provider_name, force=True)
    return {"ok": True, **result}


@router.post("/recommendations/{email_id}/block")
def frontend_block_recommendation(
    email_id: str,
    payload: FrontendRecommendationActionRequest,
    authorization: Optional[str] = Header(default=None),
):
    run_id, provider_name = _ensure_frontend_run()
    detail = _find_recommendation_detail(run_id, email_id)
    recommendation = _frontend_recommendation_payload(detail, blocked=True)
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    blocked.add(email_id)

    decision = AutomationDecision(
        email_id=email_id,
        proposed_action=payload.action,
        final_action="blocked",
        approved_by_user=bool(_extract_bearer_token(authorization)),
        reason=recommendation["reason"],
        confidence=recommendation["confidence"],
        safety_verifier_status=SafetyStatus.blocked,
    )
    audit_entry = AuditLogger().create_entry(decision)
    with session_scope() as session:
        InboxRepository(session).add_audit_entry(audit_entry)

    STREAM_HUB.emit(
        {
            "type": "recommendation_blocked",
            "provider": provider_name,
            "run_id": run_id,
            "email_id": email_id,
        }
    )
    return {"ok": True, "emailId": email_id, "action": payload.action, "finalAction": "blocked"}


@router.get("/health/webhook")
def frontend_webhook_health():
    now = datetime.now(timezone.utc)
    return {
        "status": "healthy",
        "last_event_at": STREAM_HUB.last_event_at.isoformat() if STREAM_HUB.last_event_at else None,
        "uptime_seconds": int((now - STREAM_HUB.started_at).total_seconds()),
        "connected_clients": len(STREAM_HUB.subscribers),
    }


@router.get("/stream/emails")
async def frontend_email_stream():
    queue = STREAM_HUB.subscribe()

    async def event_generator():
        try:
            initial = json.dumps(
                {
                    "type": "connected",
                    "at": datetime.now(timezone.utc).isoformat(),
                }
            )
            yield f"data: {initial}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {message}\n\n"
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            STREAM_HUB.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
