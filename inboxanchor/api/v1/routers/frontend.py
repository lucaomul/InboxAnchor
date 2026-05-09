from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from inboxanchor.bootstrap import InboxAnchorService
from inboxanchor.core.time_windows import (
    ALL_TIME_RANGE,
    available_time_ranges,
    normalize_time_range,
    time_range_label,
)
from inboxanchor.infra.audit_log import AuditLogger
from inboxanchor.infra.auth import AuthService
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.models import AutomationDecision, SafetyStatus, WorkspaceSettings

router = APIRouter(tags=["frontend-compat"])

FRONTEND_RUN_CACHE: dict[str, str] = {}
FRONTEND_SERVICE_CACHE: dict[str, InboxAnchorService] = {}
FRONTEND_BLOCK_REGISTRY: dict[str, set[str]] = {}
FRONTEND_FORCE_REFRESH_PROVIDERS: set[str] = set()
FRONTEND_PROVIDER_ERRORS: dict[str, str] = {}
FRONTEND_PROGRESS: dict[str, dict] = {}
FRONTEND_ACTIVE_RUNS: dict[str, "FrontendRunJob"] = {}
FRONTEND_ACTIVE_RUNS_LOCK = threading.Lock()
MAILBOX_BACKFILL_SYNC_KIND = "mailbox_backfill"


@dataclass
class FrontendRunJob:
    provider_name: str
    event: threading.Event = field(default_factory=threading.Event)
    run_id: Optional[str] = None
    error: Optional[str] = None


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
    time_range: Optional[str] = None


class FrontendMailboxBackfillRequest(BaseModel):
    provider: Optional[str] = None
    force_refresh: bool = False
    limit: int = Field(default=5000, ge=25, le=20000)
    batch_size: int = Field(default=250, ge=10, le=1000)
    include_body: bool = False
    unread_only: bool = False
    time_range: Optional[str] = None


def _scope_key(provider_name: str, time_range: Optional[str]) -> str:
    return f"{provider_name}::{normalize_time_range(time_range)}"


def _scope_sync_kind(time_range: Optional[str]) -> str:
    normalized = normalize_time_range(time_range)
    if normalized == ALL_TIME_RANGE:
        return MAILBOX_BACKFILL_SYNC_KIND
    return f"{MAILBOX_BACKFILL_SYNC_KIND}:{normalized}"


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
    if provider:
        return provider.lower()

    preferred = (settings.preferred_provider or "fake").lower()
    if preferred != "fake":
        return preferred

    for candidate in ("gmail", "imap", "yahoo", "outlook"):
        connection = service.load_provider_connection(candidate)
        if connection.sync_enabled and connection.status in {"configured", "connected"}:
            return candidate

    return preferred


def _get_workspace_settings() -> WorkspaceSettings:
    return InboxAnchorService().load_workspace_settings()


def _service_for_provider(provider_name: str) -> InboxAnchorService:
    service = FRONTEND_SERVICE_CACHE.get(provider_name)
    if service is None:
        service = InboxAnchorService(provider_name=provider_name)
        FRONTEND_SERVICE_CACHE[provider_name] = service
    return service


def mark_frontend_provider_dirty(provider_name: str) -> None:
    FRONTEND_SERVICE_CACHE.pop(provider_name, None)
    FRONTEND_BLOCK_REGISTRY.pop(provider_name, None)
    for registry in (FRONTEND_RUN_CACHE, FRONTEND_PROVIDER_ERRORS, FRONTEND_PROGRESS):
        registry.pop(provider_name, None)
        for key in [item for item in registry if item.startswith(f"{provider_name}::")]:
            registry.pop(key, None)
    with FRONTEND_ACTIVE_RUNS_LOCK:
        for key in [item for item in FRONTEND_ACTIVE_RUNS if item.startswith(f"{provider_name}::")]:
            FRONTEND_ACTIVE_RUNS.pop(key, None)
    FRONTEND_FORCE_REFRESH_PROVIDERS.add(provider_name)


def _provider_runtime_error_message(provider_name: str, exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    if "gmail.googleapis.com" in message:
        return (
            "Gmail connected, but InboxAnchor could not reach gmail.googleapis.com from the "
            "backend, so the unread scan never completed. Check the backend machine's "
            "internet/DNS access, then retry Refresh unread scan."
        )
    if provider_name == "gmail":
        return f"Gmail connected, but InboxAnchor could not fetch unread mail: {message}"
    if provider_name in {"imap", "yahoo", "outlook"}:
        return (
            f"{provider_name.upper()} connected, but InboxAnchor could not fetch unread "
            f"mail: {message}"
        )
    return f"InboxAnchor could not refresh the live mailbox: {message}"


def _raise_provider_runtime_error(provider_name: str, exc: Exception) -> None:
    message = _provider_runtime_error_message(provider_name, exc)
    raise HTTPException(status_code=502, detail=message) from exc


def _update_frontend_progress(
    provider_name: str,
    payload: dict,
    *,
    time_range: Optional[str] = None,
) -> None:
    normalized_time_range = normalize_time_range(time_range or payload.get("time_range"))
    scope_key = _scope_key(provider_name, normalized_time_range)
    previous = FRONTEND_PROGRESS.get(scope_key, {})
    progress = {
        "provider": provider_name,
        "time_range": normalized_time_range,
        "time_range_label": time_range_label(normalized_time_range),
        "mode": previous.get("mode", "scan"),
        "status": previous.get("status", "running"),
        "stage": previous.get("stage", "starting"),
        "target_count": previous.get("target_count", 0),
        "processed_count": previous.get("processed_count", 0),
        "read_count": previous.get("read_count", 0),
        "action_item_count": previous.get("action_item_count", 0),
        "recommendation_count": previous.get("recommendation_count", 0),
        "batch_count": previous.get("batch_count", 0),
        "cached_count": previous.get("cached_count", 0),
        "hydrated_count": previous.get("hydrated_count", 0),
        "oldest_cached_at": previous.get("oldest_cached_at"),
        "newest_cached_at": previous.get("newest_cached_at"),
        "latest_subject": previous.get("latest_subject"),
        "resume_offset": previous.get("resume_offset", 0),
        "remaining_count": previous.get("remaining_count", 0),
        "completed": previous.get("completed", False),
        "run_id": previous.get("run_id"),
        "error": previous.get("error"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if "mode" in payload:
        progress["mode"] = payload["mode"]
    if "status" in payload:
        progress["status"] = payload["status"]
    if "stage" in payload:
        progress["stage"] = payload["stage"]
    if "limit" in payload:
        progress["target_count"] = payload["limit"]
    if "processed_emails" in payload:
        progress["processed_count"] = payload["processed_emails"]
    if "read_count" in payload:
        progress["read_count"] = payload["read_count"]
    if "action_item_count" in payload:
        progress["action_item_count"] = payload["action_item_count"]
    if "recommendation_count" in payload:
        progress["recommendation_count"] = payload["recommendation_count"]
    if "batch_count" in payload:
        progress["batch_count"] = payload["batch_count"]
    if "cached_count" in payload:
        progress["cached_count"] = payload["cached_count"]
    if "hydrated_count" in payload:
        progress["hydrated_count"] = payload["hydrated_count"]
    if "oldest_cached_at" in payload:
        progress["oldest_cached_at"] = payload["oldest_cached_at"]
    if "newest_cached_at" in payload:
        progress["newest_cached_at"] = payload["newest_cached_at"]
    if "latest_subject" in payload:
        progress["latest_subject"] = payload["latest_subject"]
    if "resume_offset" in payload:
        progress["resume_offset"] = payload["resume_offset"]
    if "remaining_count" in payload:
        progress["remaining_count"] = payload["remaining_count"]
    if "completed" in payload:
        progress["completed"] = payload["completed"]
    if "run_id" in payload:
        progress["run_id"] = payload["run_id"]
    if "error" in payload:
        progress["error"] = payload["error"]
    FRONTEND_PROGRESS[scope_key] = progress
    if progress["error"]:
        FRONTEND_PROVIDER_ERRORS[scope_key] = progress["error"]
    else:
        FRONTEND_PROVIDER_ERRORS.pop(scope_key, None)
    if progress["status"] == "running":
        STREAM_HUB.emit(
            {
                "type": "backfill_progress" if progress["mode"] == "backfill" else "scan_progress",
                **progress,
            }
        )


def _wait_for_frontend_job(
    job: FrontendRunJob,
    provider_name: str,
    *,
    time_range: Optional[str] = None,
) -> tuple[str, str]:
    scope_key = _scope_key(provider_name, time_range)
    completed = job.event.wait(timeout=180)
    if not completed:
        message = (
            f"InboxAnchor timed out while preparing the live {provider_name} inbox. "
            "Retry the unread scan."
        )
        _update_frontend_progress(
            provider_name,
            {
                "status": "error",
                "stage": "timeout",
                "error": message,
            },
            time_range=time_range,
        )
        raise HTTPException(status_code=504, detail=message)
    if job.error:
        raise HTTPException(status_code=502, detail=job.error)
    if not job.run_id:
        raise HTTPException(status_code=500, detail="Frontend run finished without a run id.")
    FRONTEND_RUN_CACHE[scope_key] = job.run_id
    return job.run_id, provider_name


def _provider_has_live_sync(service: InboxAnchorService, provider_name: str) -> bool:
    if provider_name == "fake":
        return False
    connection = service.load_provider_connection(provider_name)
    return connection.sync_enabled and connection.status in {"configured", "connected"}


def _zero_run_needs_refresh(
    service: InboxAnchorService,
    repository: InboxRepository,
    provider_name: str,
    run_id: str,
    *,
    time_range: Optional[str] = None,
) -> bool:
    if not _provider_has_live_sync(service, provider_name):
        return False
    if repository.count_run_email_details(run_id) > 0:
        return False
    try:
        unread_probe = service.provider.list_unread(
            limit=1,
            include_body=False,
            time_range=time_range,
        )
    except Exception as exc:
        _raise_provider_runtime_error(provider_name, exc)
    return len(unread_probe) > 0


def _ensure_frontend_run(
    *,
    provider: Optional[str] = None,
    force: bool = False,
    time_range: Optional[str] = None,
) -> tuple[str, str]:
    provider_name = _get_provider_name(provider)
    normalized_time_range = normalize_time_range(time_range)
    scope_key = _scope_key(provider_name, normalized_time_range)
    if provider_name in FRONTEND_FORCE_REFRESH_PROVIDERS:
        force = True
        FRONTEND_FORCE_REFRESH_PROVIDERS.discard(provider_name)
    service = _service_for_provider(provider_name)
    settings = _get_workspace_settings()
    latest_run_id: Optional[str] = None

    with session_scope() as session:
        repository = InboxRepository(session)
        if not force:
            cached_run_id = FRONTEND_RUN_CACHE.get(scope_key)
            if cached_run_id and repository.get_run(cached_run_id):
                if _zero_run_needs_refresh(
                    service,
                    repository,
                    provider_name,
                    cached_run_id,
                    time_range=normalized_time_range,
                ):
                    FRONTEND_RUN_CACHE.pop(scope_key, None)
                else:
                    return cached_run_id, provider_name
            if normalized_time_range == ALL_TIME_RANGE:
                latest_run_id = repository.get_latest_run_id(provider_name)
                if latest_run_id:
                    if _zero_run_needs_refresh(
                        service,
                        repository,
                        provider_name,
                        latest_run_id,
                        time_range=normalized_time_range,
                    ):
                        latest_run_id = None
                    else:
                        FRONTEND_RUN_CACHE[scope_key] = latest_run_id
                        return latest_run_id, provider_name

    bootstrap_limit = min(settings.default_scan_limit, 50)
    bootstrap_batch_size = min(settings.default_batch_size, 50)
    bootstrap_email_preview_limit = min(max(settings.default_email_preview_limit, 50), 80)
    bootstrap_recommendation_preview_limit = min(
        max(settings.default_recommendation_preview_limit, 60),
        120,
    )
    initial_load = not force and latest_run_id is None

    wait_job: Optional[FrontendRunJob] = None
    with FRONTEND_ACTIVE_RUNS_LOCK:
        active_job = FRONTEND_ACTIVE_RUNS.get(scope_key)
        if active_job is not None:
            wait_job = active_job
        else:
            job = FrontendRunJob(provider_name=provider_name)
            FRONTEND_ACTIVE_RUNS[scope_key] = job

    if wait_job is not None:
        return _wait_for_frontend_job(wait_job, provider_name, time_range=normalized_time_range)

    _update_frontend_progress(
        provider_name,
        {
            "mode": "scan",
            "status": "running",
            "stage": "bootstrapping" if initial_load else "refreshing",
            "limit": bootstrap_limit if initial_load else settings.default_scan_limit,
            "processed_emails": 0,
            "read_count": 0,
            "action_item_count": 0,
            "recommendation_count": 0,
            "batch_count": 0,
            "run_id": latest_run_id,
            "error": None,
        },
        time_range=normalized_time_range,
    )

    try:
        result = service.engine.run(
            dry_run=True,
            limit=bootstrap_limit if initial_load else settings.default_scan_limit,
            batch_size=bootstrap_batch_size if initial_load else settings.default_batch_size,
            confidence_threshold=settings.default_confidence_threshold,
            email_preview_limit=(
                bootstrap_email_preview_limit
                if initial_load
                else max(
                    settings.default_email_preview_limit,
                    min(settings.default_scan_limit, 500),
                )
            ),
            recommendation_preview_limit=(
                bootstrap_recommendation_preview_limit
                if initial_load
                else max(
                    settings.default_recommendation_preview_limit,
                    min(settings.default_scan_limit, 750),
                )
            ),
            workspace_policy=settings.policy,
            progress_callback=lambda payload: _update_frontend_progress(
                provider_name,
                payload,
                time_range=normalized_time_range,
            ),
            time_range=normalized_time_range,
        )
    except HTTPException:
        job.error = "InboxAnchor could not prepare the live mailbox."
        job.event.set()
        with FRONTEND_ACTIVE_RUNS_LOCK:
            FRONTEND_ACTIVE_RUNS.pop(scope_key, None)
        raise
    except Exception as exc:
        message = _provider_runtime_error_message(provider_name, exc)
        job.error = message
        _update_frontend_progress(
            provider_name,
            {
                "mode": "scan",
                "status": "error",
                "stage": "failed",
                "error": message,
            },
            time_range=normalized_time_range,
        )
        job.event.set()
        with FRONTEND_ACTIVE_RUNS_LOCK:
            FRONTEND_ACTIVE_RUNS.pop(scope_key, None)
        raise HTTPException(status_code=502, detail=message) from exc

    FRONTEND_RUN_CACHE[scope_key] = result.run_id
    scanned_emails = getattr(
        result,
        "scanned_emails",
        getattr(result, "total_emails", 0),
    )
    total_emails = getattr(result, "total_emails", scanned_emails)
    action_items = getattr(result, "action_items", {})
    recommendations = getattr(result, "recommendations", [])
    batch_count = getattr(result, "batch_count", 0)
    _update_frontend_progress(
        provider_name,
        {
            "mode": "scan",
            "status": "complete",
            "stage": "ready",
            "limit": scanned_emails,
            "processed_emails": total_emails,
            "read_count": scanned_emails,
            "action_item_count": sum(len(items) for items in action_items.values()),
            "recommendation_count": len(recommendations),
            "batch_count": batch_count,
            "run_id": result.run_id,
            "error": None,
        },
        time_range=normalized_time_range,
    )
    job.run_id = result.run_id
    job.event.set()
    with FRONTEND_ACTIVE_RUNS_LOCK:
        FRONTEND_ACTIVE_RUNS.pop(scope_key, None)
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


def _frontend_email_payload(detail: dict, mailbox_email: Optional[dict] = None) -> dict:
    body_preview = detail.get("body_preview", "")
    body_full = (mailbox_email or {}).get("body_full", body_preview)
    return {
        "id": detail["email_id"],
        "threadId": detail["thread_id"],
        "sender": detail["sender"],
        "subject": detail["subject"],
        "snippet": detail["snippet"],
        "bodyPreview": body_preview,
        "bodyFull": body_full,
        "receivedAt": detail["received_at"],
        "labels": detail["labels"],
        "hasAttachments": detail["has_attachments"],
        "unread": detail["unread"],
        "classification": _frontend_classification_payload(detail),
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


def _load_mailbox_email_map(provider_name: str, email_ids: list[str]) -> dict[str, dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.get_mailbox_email_map(provider_name, email_ids)


def _load_mailbox_cache_stats(provider_name: str, *, time_range: Optional[str] = None) -> dict:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.get_mailbox_cache_stats(
            provider_name,
            time_range=normalize_time_range(time_range),
        )


def _load_mailbox_sync_state(
    provider_name: str,
    *,
    time_range: Optional[str] = None,
) -> Optional[dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.get_provider_sync_state(
            provider_name,
            _scope_sync_kind(time_range),
        )


def _get_cached_or_latest_run_id(
    provider_name: str,
    *,
    time_range: Optional[str] = None,
) -> Optional[str]:
    normalized_time_range = normalize_time_range(time_range)
    cached = FRONTEND_RUN_CACHE.get(_scope_key(provider_name, normalized_time_range))
    if cached:
        return cached
    if normalized_time_range != ALL_TIME_RANGE:
        return None
    with session_scope() as session:
        return InboxRepository(session).get_latest_run_id(provider_name)


def _hydrate_mailbox_email_if_needed(
    provider_name: str,
    email_id: str,
    detail: dict,
    mailbox_email: Optional[dict],
) -> Optional[dict]:
    if provider_name == "fake":
        return mailbox_email
    if mailbox_email and (mailbox_email.get("body_full") or "").strip():
        return mailbox_email

    service = _service_for_provider(provider_name)
    try:
        body_full = service.provider.fetch_email_body(email_id)
    except Exception as exc:
        _raise_provider_runtime_error(provider_name, exc)

    with session_scope() as session:
        hydrated = InboxRepository(session).save_mailbox_email_body(
            provider_name,
            email_id,
            body_full=body_full,
            body_preview=(body_full or detail.get("body_preview", ""))[:500],
        )
    return hydrated or mailbox_email


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
    try:
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
    except HTTPException:
        raise
    except Exception as exc:
        _raise_provider_runtime_error(provider_name, exc)

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


def _build_ops_overview(
    provider_name: str,
    run_id: str,
    *,
    time_range: Optional[str] = None,
) -> dict:
    normalized_time_range = normalize_time_range(time_range)
    settings = _get_workspace_settings()
    digest = _load_digest(run_id)
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    connection = InboxAnchorService().load_provider_connection(provider_name)
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    sync_state = _load_mailbox_sync_state(provider_name, time_range=normalized_time_range)
    historical_target = min(max(settings.default_scan_limit * 4, 5000), 20000)
    mailbox_target = (
        max(historical_target, int(sync_state.get("target_count") or 0))
        if sync_state
        else historical_target
    )
    processed_total = max(
        cache_stats["cached_count"],
        int(sync_state.get("processed_count") or 0) if sync_state else 0,
    )
    resume_offset = min(
        int(sync_state.get("next_offset") or processed_total) if sync_state else processed_total,
        mailbox_target,
    )
    mailbox_memory = {
        "targetCount": mailbox_target,
        "processedTotal": processed_total,
        "resumeOffset": resume_offset,
        "remainingCount": max(mailbox_target - resume_offset, 0),
        "completed": bool(sync_state.get("completed")) if sync_state else False,
        "includeBody": bool(sync_state.get("include_body")) if sync_state else False,
        "unreadOnly": bool(sync_state.get("unread_only")) if sync_state else False,
        "lastBackfillAt": sync_state.get("updated_at") if sync_state else None,
    }
    with session_scope() as session:
        repository = InboxRepository(session)
        safe_count = repository.count_run_recommendations_by_status(run_id, "safe")
        review_count = repository.count_run_recommendations_by_status(run_id, "requires_approval")
        blocked_count = repository.count_run_recommendations_by_status(run_id, "blocked")
        auto_label_candidates = repository.count_run_auto_label_candidates(run_id)
        high_priority_count = repository.count_run_high_priority_emails(run_id)
        attachment_count = repository.count_run_attachment_emails(run_id)

    return {
        "provider": provider_name,
        "timeRange": normalized_time_range,
        "timeRangeLabel": time_range_label(normalized_time_range),
        "timeRangeOptions": available_time_ranges(),
        "runId": run_id,
        "unreadCount": digest["total_unread"],
        "highPriorityCount": high_priority_count,
        "safeCleanupCount": safe_count,
        "needsApprovalCount": review_count,
        "blockedCount": blocked_count + len(blocked),
        "autoLabelCandidates": auto_label_candidates,
        "attachmentsCount": attachment_count,
        "cachedEmailsCount": cache_stats["cached_count"],
        "cachedUnreadCount": cache_stats["cached_unread_count"],
        "hydratedEmailsCount": cache_stats["hydrated_count"],
        "oldestCachedAt": cache_stats["oldest_cached_at"],
        "newestCachedAt": cache_stats["newest_cached_at"],
        "mailboxMemory": mailbox_memory,
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
                "impact": (
                    f"Scans up to {settings.default_scan_limit} unread emails in "
                    f"{time_range_label(normalized_time_range).lower()}."
                ),
            },
            {
                "slug": "backfill",
                "label": "Build mailbox memory",
                "description": (
                    "Index older mailbox history into the local cache without forcing "
                    "a huge live triage run."
                ),
                "impact": (
                    f"Cache up to {mailbox_target} historical emails for "
                    f"{time_range_label(normalized_time_range).lower()} so search, "
                    "hydration, and future syncs have more context."
                ),
            },
            {
                "slug": "auto-label",
                "label": "Auto-label unread mail",
                "description": "Apply category, urgency, attachment, and action labels.",
                "impact": (
                    f"{auto_label_candidates} unread emails in "
                    f"{time_range_label(normalized_time_range).lower()} can receive helpful "
                    "labels right now."
                ),
            },
            {
                "slug": "safe-cleanup",
                "label": "Run safe cleanup",
                "description": "Apply only low-risk mark-read and archive actions.",
                "impact": (
                    f"{safe_count} recommendations in "
                    f"{time_range_label(normalized_time_range).lower()} are safe to execute "
                    "immediately."
                ),
            },
            {
                "slug": "full-anchor",
                "label": "Mailbox upgrade sweep",
                "description": "Label first, then run safe cleanup on the same unread set.",
                "impact": (
                    f"Best for making {time_range_label(normalized_time_range).lower()} in "
                    "Gmail, Yahoo, and IMAP inboxes visibly cleaner without unsafe deletion."
                ),
            },
        ],
    }


@router.get("/emails")
def frontend_emails(
    q: str = "",
    category: str = "",
    priority: str = "",
    time_range: str = "",
    unread_only: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
):
    run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
    with session_scope() as session:
        repository = InboxRepository(session)
        total = repository.count_run_email_details(
            run_id,
            priority=priority or None,
            category=category or None,
            q=q or None,
            unread_only=unread_only,
            time_range=time_range or None,
        )
        page = repository.list_run_email_details(
            run_id,
            limit=limit,
            offset=offset,
            priority=priority or None,
            category=category or None,
            q=q or None,
            unread_only=unread_only,
            time_range=time_range or None,
        )
    mailbox_map = _load_mailbox_email_map(provider_name, [item["email_id"] for item in page])
    return {
        "emails": [
            _frontend_email_payload(item, mailbox_map.get(item["email_id"]))
            for item in page
        ],
        "total": total,
    }


@router.get("/emails/{email_id}")
def frontend_email(email_id: str, time_range: str = ""):
    run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
    with session_scope() as session:
        detail = InboxRepository(session).get_run_email_detail(run_id, email_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Email not found")
    mailbox_map = _load_mailbox_email_map(provider_name, [email_id])
    mailbox_email = _hydrate_mailbox_email_if_needed(
        provider_name,
        email_id,
        detail,
        mailbox_map.get(email_id),
    )
    return _frontend_email_payload(detail, mailbox_email)


@router.get("/classifications")
def frontend_classifications(time_range: str = ""):
    run_id, _ = _ensure_frontend_run(time_range=time_range or None)
    details = _load_email_details(run_id)
    return {
        item["email_id"]: _frontend_classification_payload(item)
        for item in details
    }


@router.get("/recommendations")
def frontend_recommendations(email_id: str = "", time_range: str = ""):
    run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    if email_id:
        with session_scope() as session:
            detail = InboxRepository(session).get_run_recommendation_detail(run_id, email_id)
        details = [detail] if detail else []
    else:
        details = _load_recommendation_details(run_id)
    return [
        _frontend_recommendation_payload(item, blocked=item["email_id"] in blocked)
        for item in details
    ]


@router.get("/emails/{email_id}/actions")
def frontend_action_items(email_id: str, time_range: str = ""):
    run_id, _ = _ensure_frontend_run(time_range=time_range or None)
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
def frontend_digest(time_range: str = ""):
    run_id, _ = _ensure_frontend_run(time_range=time_range or None)
    digest = _load_digest(run_id)
    return {
        "totalUnread": digest["total_unread"],
        "categoryCounts": digest["category_counts"],
        "highPriorityIds": digest["high_priority_ids"],
        "summary": digest["summary"],
    }


@router.get("/ops/overview")
def frontend_ops_overview(provider: str = "", time_range: str = ""):
    run_id, provider_name = _ensure_frontend_run(
        provider=provider or None,
        time_range=time_range or None,
    )
    return _build_ops_overview(provider_name, run_id, time_range=time_range or None)


@router.get("/ops/progress")
def frontend_ops_progress(provider: str = "", time_range: str = ""):
    provider_name = _get_provider_name(provider or None)
    normalized_time_range = normalize_time_range(time_range or None)
    scope_key = _scope_key(provider_name, normalized_time_range)
    progress = FRONTEND_PROGRESS.get(scope_key)
    if progress:
        return progress
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    sync_state = _load_mailbox_sync_state(provider_name, time_range=normalized_time_range)
    if sync_state:
        target_count = int(sync_state.get("target_count") or 0)
        processed_count = int(sync_state.get("processed_count") or 0)
        resume_offset = int(sync_state.get("next_offset") or processed_count)
        completed = bool(sync_state.get("completed"))
        return {
            "provider": provider_name,
            "time_range": normalized_time_range,
            "time_range_label": time_range_label(normalized_time_range),
            "mode": "backfill",
            "status": "complete" if completed else "paused",
            "stage": "backfill_ready" if completed else "backfill_resume",
            "target_count": target_count,
            "processed_count": processed_count,
            "read_count": processed_count,
            "action_item_count": 0,
            "recommendation_count": 0,
            "batch_count": int(sync_state.get("batch_count") or 0),
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": cache_stats["hydrated_count"],
            "oldest_cached_at": cache_stats["oldest_cached_at"],
            "newest_cached_at": cache_stats["newest_cached_at"],
            "latest_subject": sync_state.get("latest_subject"),
            "resume_offset": resume_offset,
            "remaining_count": max(target_count - resume_offset, 0),
            "completed": completed,
            "run_id": FRONTEND_RUN_CACHE.get(scope_key),
            "error": FRONTEND_PROVIDER_ERRORS.get(scope_key),
            "updated_at": sync_state.get("updated_at", datetime.now(timezone.utc).isoformat()),
        }
    return {
        "provider": provider_name,
        "time_range": normalized_time_range,
        "time_range_label": time_range_label(normalized_time_range),
        "mode": "scan",
        "status": "idle",
        "stage": "idle",
        "target_count": 0,
        "processed_count": 0,
        "read_count": 0,
        "action_item_count": 0,
        "recommendation_count": 0,
        "batch_count": 0,
        "cached_count": 0,
        "hydrated_count": 0,
        "oldest_cached_at": None,
        "newest_cached_at": None,
        "latest_subject": None,
        "resume_offset": 0,
        "remaining_count": 0,
        "completed": False,
        "run_id": FRONTEND_RUN_CACHE.get(scope_key),
        "error": FRONTEND_PROVIDER_ERRORS.get(scope_key),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/ops/scan")
def frontend_ops_scan(payload: FrontendProviderWorkflowRequest):
    run_id, provider_name = _ensure_frontend_run(
        provider=payload.provider,
        force=payload.force_refresh,
        time_range=payload.time_range,
    )
    overview = _build_ops_overview(provider_name, run_id, time_range=payload.time_range)
    STREAM_HUB.emit(
        {
            "type": "scan_completed",
            "provider": provider_name,
            "run_id": run_id,
        }
    )
    return overview


@router.post("/ops/backfill")
def frontend_ops_backfill(payload: FrontendMailboxBackfillRequest):
    provider_name = _get_provider_name(payload.provider)
    normalized_time_range = normalize_time_range(payload.time_range)
    sync_kind = _scope_sync_kind(normalized_time_range)
    service = _service_for_provider(provider_name)
    start_offset = 0
    processed_total = 0
    processed_this_run = 0
    hydrated_total = 0
    batch_count = 0
    latest_subject: Optional[str] = None

    with session_scope() as session:
        repository = InboxRepository(session)
        if payload.force_refresh:
            repository.clear_provider_sync_state(provider_name, sync_kind)
        sync_state = repository.get_provider_sync_state(provider_name, sync_kind)
        cache_stats = repository.get_mailbox_cache_stats(
            provider_name,
            time_range=normalized_time_range,
        )

    if (
        sync_state
        and not payload.force_refresh
        and bool(sync_state.get("include_body")) == payload.include_body
        and bool(sync_state.get("unread_only")) == payload.unread_only
        and normalize_time_range(sync_state.get("time_range")) == normalized_time_range
    ):
        start_offset = min(
            int(sync_state.get("next_offset") or sync_state.get("processed_count") or 0),
            payload.limit,
        )
        processed_total = int(sync_state.get("processed_count") or start_offset)
        hydrated_total = max(
            int(sync_state.get("hydrated_count") or 0),
            cache_stats["hydrated_count"],
        )
        batch_count = int(sync_state.get("batch_count") or 0)
        latest_subject = sync_state.get("latest_subject")
        if bool(sync_state.get("completed")) and start_offset >= payload.limit:
            run_id = _get_cached_or_latest_run_id(
                provider_name,
                time_range=normalized_time_range,
            )
            if run_id is None:
                run_id, _ = _ensure_frontend_run(
                    provider=provider_name,
                    time_range=normalized_time_range,
                )
            overview = _build_ops_overview(
                provider_name,
                run_id,
                time_range=normalized_time_range,
            )
            _update_frontend_progress(
                provider_name,
                {
                    "mode": "backfill",
                    "status": "complete",
                    "stage": "backfill_ready",
                    "limit": payload.limit,
                    "processed_emails": processed_total,
                    "read_count": processed_total,
                    "batch_count": batch_count,
                    "cached_count": cache_stats["cached_count"],
                    "hydrated_count": cache_stats["hydrated_count"],
                    "oldest_cached_at": cache_stats["oldest_cached_at"],
                    "newest_cached_at": cache_stats["newest_cached_at"],
                    "latest_subject": latest_subject,
                    "resume_offset": start_offset,
                    "remaining_count": 0,
                    "completed": True,
                    "error": None,
                },
                time_range=normalized_time_range,
            )
            return {
                "count": 0,
                "processedTotal": processed_total,
                "cachedCount": cache_stats["cached_count"],
                "hydratedCount": cache_stats["hydrated_count"],
                "resumeOffset": start_offset,
                "remainingCount": 0,
                "completed": True,
                "overview": overview,
            }

    _update_frontend_progress(
        provider_name,
        {
            "mode": "backfill",
            "status": "running",
            "stage": "backfill_resume" if start_offset else "backfill_index",
            "limit": payload.limit,
            "processed_emails": processed_total,
            "read_count": processed_total,
            "action_item_count": 0,
            "recommendation_count": 0,
            "batch_count": batch_count,
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": cache_stats["hydrated_count"],
            "oldest_cached_at": cache_stats["oldest_cached_at"],
            "newest_cached_at": cache_stats["newest_cached_at"],
            "latest_subject": latest_subject,
            "resume_offset": start_offset,
            "remaining_count": max(payload.limit - start_offset, 0),
            "completed": False,
            "error": None,
        },
        time_range=normalized_time_range,
    )

    try:
        for batch in service.provider.iter_mailbox_batches(
            limit=max(payload.limit - start_offset, 0),
            batch_size=payload.batch_size,
            include_body=payload.include_body,
            unread_only=payload.unread_only,
            offset=start_offset,
            time_range=normalized_time_range,
        ):
            batch_count += 1
            with session_scope() as session:
                repository = InboxRepository(session)
                for email in batch:
                    repository.upsert_mailbox_email(provider_name, email)
                    processed_this_run += 1
                    processed_total += 1
                    if (email.body_full or "").strip():
                        hydrated_total += 1
                cache_stats = repository.get_mailbox_cache_stats(
                    provider_name,
                    time_range=normalized_time_range,
                )
                repository.save_provider_sync_state(
                    provider_name,
                    sync_kind,
                    {
                        "target_count": payload.limit,
                        "processed_count": processed_total,
                        "next_offset": processed_total,
                        "batch_count": batch_count,
                        "hydrated_count": max(hydrated_total, cache_stats["hydrated_count"]),
                        "cached_count": cache_stats["cached_count"],
                        "include_body": payload.include_body,
                        "unread_only": payload.unread_only,
                        "time_range": normalized_time_range,
                        "completed": False,
                        "latest_subject": batch[0].subject if batch else latest_subject,
                    },
                )
            latest_subject = batch[0].subject if batch else latest_subject
            _update_frontend_progress(
                provider_name,
                {
                    "mode": "backfill",
                    "status": "running",
                    "stage": "backfill_resume" if start_offset else "backfill_index",
                    "limit": payload.limit,
                    "processed_emails": processed_total,
                    "read_count": processed_total,
                    "batch_count": batch_count,
                    "cached_count": cache_stats["cached_count"],
                    "hydrated_count": max(hydrated_total, cache_stats["hydrated_count"]),
                    "oldest_cached_at": cache_stats["oldest_cached_at"],
                    "newest_cached_at": cache_stats["newest_cached_at"],
                    "latest_subject": latest_subject,
                    "resume_offset": processed_total,
                    "remaining_count": max(payload.limit - processed_total, 0),
                    "completed": False,
                },
                time_range=normalized_time_range,
            )
    except NotImplementedError as exc:
        message = str(exc)
        _update_frontend_progress(
            provider_name,
            {
                "mode": "backfill",
                "status": "error",
                "stage": "unsupported",
                "error": message,
            },
            time_range=normalized_time_range,
        )
        raise HTTPException(status_code=400, detail=message) from exc
    except Exception as exc:
        message = _provider_runtime_error_message(provider_name, exc)
        _update_frontend_progress(
            provider_name,
            {
                "mode": "backfill",
                "status": "error",
                "stage": "failed",
                "error": message,
            },
            time_range=normalized_time_range,
        )
        raise HTTPException(status_code=502, detail=message) from exc

    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    completed = processed_total >= payload.limit or processed_this_run == 0
    with session_scope() as session:
        repository = InboxRepository(session)
        repository.save_provider_sync_state(
            provider_name,
            sync_kind,
            {
                "target_count": payload.limit,
                "processed_count": processed_total,
                "next_offset": min(processed_total, payload.limit),
                "batch_count": batch_count,
                "hydrated_count": max(hydrated_total, cache_stats["hydrated_count"]),
                "cached_count": cache_stats["cached_count"],
                "include_body": payload.include_body,
                "unread_only": payload.unread_only,
                "time_range": normalized_time_range,
                "completed": completed,
                "latest_subject": latest_subject,
            },
        )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "backfill",
            "status": "complete",
            "stage": "backfill_ready",
            "limit": payload.limit,
            "processed_emails": processed_total,
            "read_count": processed_total,
            "batch_count": batch_count,
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": cache_stats["hydrated_count"],
            "oldest_cached_at": cache_stats["oldest_cached_at"],
            "newest_cached_at": cache_stats["newest_cached_at"],
            "latest_subject": latest_subject,
            "resume_offset": min(processed_total, payload.limit),
            "remaining_count": max(payload.limit - processed_total, 0),
            "completed": completed,
            "error": None,
        },
        time_range=normalized_time_range,
    )

    run_id = _get_cached_or_latest_run_id(provider_name, time_range=normalized_time_range)
    if run_id is None:
        run_id, _ = _ensure_frontend_run(
            provider=provider_name,
            time_range=normalized_time_range,
        )
    elif payload.force_refresh:
        run_id, _ = _ensure_frontend_run(
            provider=provider_name,
            force=True,
            time_range=normalized_time_range,
        )

    overview = _build_ops_overview(provider_name, run_id, time_range=normalized_time_range)
    STREAM_HUB.emit(
        {
            "type": "mailbox_backfill_completed",
            "provider": provider_name,
            "count": processed_this_run,
            "cached_count": cache_stats["cached_count"],
        }
    )
    return {
        "count": processed_this_run,
        "processedTotal": processed_total,
        "cachedCount": cache_stats["cached_count"],
        "hydratedCount": cache_stats["hydrated_count"],
        "resumeOffset": min(processed_total, payload.limit),
        "remainingCount": max(payload.limit - processed_total, 0),
        "completed": completed,
        "overview": overview,
    }


@router.post("/ops/auto-label")
def frontend_ops_auto_label(payload: FrontendProviderWorkflowRequest):
    run_id, provider_name = _ensure_frontend_run(
        provider=payload.provider,
        time_range=payload.time_range,
    )
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
        time_range=payload.time_range,
    )
    overview = _build_ops_overview(
        provider_name,
        refreshed_run_id,
        time_range=payload.time_range,
    )
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
    run_id, provider_name = _ensure_frontend_run(
        provider=payload.provider,
        time_range=payload.time_range,
    )
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
        time_range=payload.time_range,
    )
    overview = _build_ops_overview(
        provider_name,
        refreshed_run_id,
        time_range=payload.time_range,
    )
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
            time_range=payload.time_range,
        )
    )
    cleanup_result = frontend_ops_safe_cleanup(
        FrontendProviderWorkflowRequest(
            provider=payload.provider,
            force_refresh=payload.force_refresh,
            time_range=payload.time_range,
        )
    )
    return {
        "labelsApplied": label_result["count"],
        "cleanupApplied": cleanup_result["count"],
        "overview": cleanup_result["overview"],
    }


@router.post("/recommendations/apply-all-safe")
def frontend_apply_all_safe(
    authorization: Optional[str] = Header(default=None),
    time_range: str = "",
):
    run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
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

    refreshed_run_id, _ = _ensure_frontend_run(
        provider=provider_name,
        force=True,
        time_range=time_range or None,
    )
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
    time_range: str = "",
):
    run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
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
    refreshed_run_id, _ = _ensure_frontend_run(
        provider=provider_name,
        force=True,
        time_range=time_range or None,
    )
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
    time_range: str = "",
):
    run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
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
    _ensure_frontend_run(
        provider=provider_name,
        force=True,
        time_range=time_range or None,
    )
    return {"ok": True, **result}


@router.post("/recommendations/{email_id}/block")
def frontend_block_recommendation(
    email_id: str,
    payload: FrontendRecommendationActionRequest,
    authorization: Optional[str] = Header(default=None),
    time_range: str = "",
):
    run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
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
