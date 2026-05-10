from __future__ import annotations

import asyncio
import ipaddress
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from inboxanchor.agents import (
    ActionExtractorAgent,
    ClassifierAgent,
    PriorityAgent,
    SafetyVerifierAgent,
)
from inboxanchor.bootstrap import InboxAnchorService
from inboxanchor.config.settings import SETTINGS
from inboxanchor.core.rules import RulesEngine
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
from inboxanchor.infra.text_normalizer import normalize_email_body_text
from inboxanchor.mail_intelligence import (
    dedupe_labels,
    recommend_mailbox_labels,
    select_inboxanchor_labels,
    select_provider_cleanup_labels,
)
from inboxanchor.models import (
    AutomationDecision,
    EmailActionItem,
    EmailAlias,
    EmailClassification,
    EmailMessage,
    EmailRecommendation,
    SafetyStatus,
    WorkspaceSettings,
)
from inboxanchor.sender_intelligence import SenderIntelligenceResolver

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
MAILBOX_BACKFILL_BACKGROUND_THRESHOLD = 1000
MAILBOX_CLASSIFIER = ClassifierAgent()
MAILBOX_PRIORITY_AGENT = PriorityAgent()
MAILBOX_ACTION_EXTRACTOR = ActionExtractorAgent()
MAILBOX_RULES_ENGINE = RulesEngine()
MAILBOX_SAFETY_VERIFIER = SafetyVerifierAgent()


@dataclass
class FrontendRunJob:
    provider_name: str
    mode: str = "scan"
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


class FrontendReplySendRequest(BaseModel):
    body: str = Field(min_length=2, max_length=12000)


class FrontendProviderWorkflowRequest(BaseModel):
    provider: Optional[str] = None
    force_refresh: bool = True
    time_range: Optional[str] = None


class FrontendMailboxBackfillRequest(BaseModel):
    provider: Optional[str] = None
    force_refresh: bool = False
    limit: Optional[int] = Field(default=None, ge=25)
    batch_size: int = Field(default=250, ge=10, le=1000)
    include_body: bool = False
    unread_only: bool = False
    time_range: Optional[str] = None
    background: bool = True


class FrontendAliasGenerateRequest(BaseModel):
    label: str = Field(default="", max_length=128)
    purpose: str = Field(default="", max_length=512)


class AliasResolveRequest(BaseModel):
    alias_address: str = Field(min_length=3, max_length=320)
    sender: str = Field(default="", max_length=320)
    subject: str = Field(default="", max_length=998)


def _scope_key(provider_name: str, time_range: Optional[str]) -> str:
    return f"{provider_name}::{normalize_time_range(time_range)}"


def _scope_sync_kind(time_range: Optional[str]) -> str:
    normalized = normalize_time_range(time_range)
    if normalized == ALL_TIME_RANGE:
        return MAILBOX_BACKFILL_SYNC_KIND
    return f"{MAILBOX_BACKFILL_SYNC_KIND}:{normalized}"


def _mailbox_limit_remaining(limit: Optional[int], processed: int) -> int:
    if limit is None:
        return 0
    return max(limit - processed, 0)


def _mailbox_limit_reached(limit: Optional[int], processed: int) -> bool:
    return limit is not None and processed >= limit


def _mailbox_progress_target(
    limit: Optional[int],
    processed: int,
    *,
    full_mailbox_mode: bool = False,
    completed: bool = False,
) -> int:
    if limit is not None:
        return limit
    return processed if full_mailbox_mode and completed else 0


def _use_industrial_unread_sync(provider: object, *, time_range: Optional[str] = None) -> bool:
    if normalize_time_range(time_range) != ALL_TIME_RANGE:
        return False
    return callable(getattr(provider, "iter_all_unread_batches", None))


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _require_alias_resolver_secret(secret: Optional[str]) -> None:
    expected = SETTINGS.alias_resolver_secret.strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "InboxAnchor alias resolver secret is not configured. Set "
                "INBOXANCHOR_ALIAS_RESOLVER_SECRET on the backend before enabling the "
                "managed alias worker."
            ),
        )
    if not secret or secret.strip() != expected:
        raise HTTPException(status_code=401, detail="Alias resolver authentication failed.")


def _alias_resolver_secret_configured() -> bool:
    return bool(SETTINGS.alias_resolver_secret.strip())


def _managed_alias_resolver_base_url() -> str:
    return SETTINGS.alias_resolver_base_url.strip().rstrip("/")


def _managed_alias_public_backend_ready() -> bool:
    base_url = _managed_alias_resolver_base_url()
    if not base_url:
        return False
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        return False
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname or hostname in {"localhost", "127.0.0.1", "::1"}:
        return False
    if hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local)


def _current_actor_email(authorization: Optional[str]) -> str:
    token = _extract_bearer_token(authorization)
    if not token:
        return "workspace@inboxanchor.local"
    with session_scope() as session:
        auth_session = AuthService(session).get_session(token)
    if auth_session is None:
        return "workspace@inboxanchor.local"
    return auth_session.user.email


def _require_actor_email(authorization: Optional[str]) -> str:
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Log in to use this feature.")
    with session_scope() as session:
        auth_session = AuthService(session).get_session(token)
    if auth_session is None:
        raise HTTPException(status_code=401, detail="Your session expired. Log in again.")
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
    if "insufficient authentication scopes" in message.lower():
        return (
            "The connected Gmail token is missing a required permission. Reconnect Gmail from "
            "Settings so InboxAnchor can request the latest scopes for reply sending."
        )
    gmail_network_markers = (
        "httpsconnectionpool",
        "max retries exceeded",
        "failed to establish a new connection",
        "name or service not known",
        "unable to find the server",
        "temporary failure in name resolution",
        "newconnectionerror",
        "nameresolutionerror",
        "getaddrinfo failed",
        "connection aborted",
        "connection refused",
        "connection reset",
    )
    lowered = message.lower()
    if "gmail.googleapis.com" in lowered and any(
        marker in lowered for marker in gmail_network_markers
    ):
        return (
            "Gmail connected, but InboxAnchor could not reach gmail.googleapis.com from the "
            "backend, so the unread scan never completed. Check the backend machine's "
            "internet/DNS access, then retry Refresh unread scan."
        )
    if "gmail.googleapis.com" in lowered and "/labels" in lowered and "409" in lowered:
        return (
            "Gmail rejected a duplicate label create request. InboxAnchor should refresh its "
            "provider label cache and retry instead of failing the workflow."
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
        "labeled_count": previous.get("labeled_count", 0),
        "labels_removed_count": previous.get("labels_removed_count", 0),
        "archived_count": previous.get("archived_count", 0),
        "marked_read_count": previous.get("marked_read_count", 0),
        "trashed_count": previous.get("trashed_count", 0),
        "reply_sent_count": previous.get("reply_sent_count", 0),
        "oldest_cached_at": previous.get("oldest_cached_at"),
        "newest_cached_at": previous.get("newest_cached_at"),
        "latest_subject": previous.get("latest_subject"),
        "latest_action": previous.get("latest_action"),
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
        progress["target_count"] = int(payload["limit"] or 0)
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
    if "labeled_count" in payload:
        progress["labeled_count"] = payload["labeled_count"]
    if "labels_removed_count" in payload:
        progress["labels_removed_count"] = payload["labels_removed_count"]
    if "archived_count" in payload:
        progress["archived_count"] = payload["archived_count"]
    if "marked_read_count" in payload:
        progress["marked_read_count"] = payload["marked_read_count"]
    if "trashed_count" in payload:
        progress["trashed_count"] = payload["trashed_count"]
    if "reply_sent_count" in payload:
        progress["reply_sent_count"] = payload["reply_sent_count"]
    if "oldest_cached_at" in payload:
        progress["oldest_cached_at"] = payload["oldest_cached_at"]
    if "newest_cached_at" in payload:
        progress["newest_cached_at"] = payload["newest_cached_at"]
    if "latest_subject" in payload:
        progress["latest_subject"] = payload["latest_subject"]
    if "latest_action" in payload:
        progress["latest_action"] = payload["latest_action"]
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
    if normalize_time_range(time_range) != ALL_TIME_RANGE:
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
    scan_limit = bootstrap_limit if initial_load else settings.default_scan_limit
    scan_batch_size = bootstrap_batch_size if initial_load else settings.default_batch_size
    lightweight_scan = scan_limit > 250
    if lightweight_scan:
        scan_batch_size = min(scan_batch_size, 250)

    wait_job: Optional[FrontendRunJob] = None
    job, wait_job = _claim_frontend_job(
        scope_key,
        provider_name=provider_name,
        mode="scan",
    )

    if wait_job is not None:
        return _wait_for_frontend_job(wait_job, provider_name, time_range=normalized_time_range)
    assert job is not None

    _update_frontend_progress(
        provider_name,
        {
            "mode": "scan",
            "status": "running",
            "stage": "bootstrapping" if initial_load else "refreshing",
            "limit": scan_limit,
            "processed_emails": 0,
            "read_count": 0,
            "action_item_count": 0,
            "recommendation_count": 0,
            "batch_count": 0,
            "labeled_count": 0,
            "archived_count": 0,
            "marked_read_count": 0,
            "trashed_count": 0,
            "reply_sent_count": 0,
            "run_id": latest_run_id,
            "error": None,
        },
        time_range=normalized_time_range,
    )

    try:
        result = service.engine.run(
            dry_run=True,
            limit=scan_limit,
            batch_size=scan_batch_size,
            include_body=not lightweight_scan,
            extract_actions=not lightweight_scan,
            draft_replies=not lightweight_scan,
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
            "labeled_count": 0,
            "archived_count": 0,
            "marked_read_count": 0,
            "trashed_count": 0,
            "reply_sent_count": 0,
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


def _frontend_recommendation_payload(detail: dict, *, blocked: bool = False) -> dict:
    classification = detail["classification"]
    priority = classification["priority"]
    recommended_action = detail["recommended_action"]

    proposed_labels = dedupe_labels(
        detail.get("proposed_labels", [])
        + _recommended_labels_for_email(detail)
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
    return recommend_mailbox_labels(
        sender=detail.get("sender", ""),
        subject=detail.get("subject", ""),
        snippet=detail.get("snippet", ""),
        body=detail.get("body_preview", ""),
        has_attachments=detail.get("has_attachments", False),
        category=classification["category"],
        priority=classification["priority"],
    )


def _reply_draft_for_email(run_id: str, email_id: str) -> Optional[str]:
    with session_scope() as session:
        payload = InboxRepository(session).get_run(run_id) or {}
    drafts = payload.get("reply_drafts", {})
    draft = drafts.get(email_id)
    if isinstance(draft, str) and draft.strip():
        return draft.strip()
    return None


def _reply_target_for_detail(detail: dict) -> str:
    sender = detail.get("sender", "")
    if "<" in sender and ">" in sender:
        candidate = sender.rsplit("<", 1)[-1].split(">", 1)[0].strip()
        if candidate:
            return candidate
    return sender.strip()


def _provider_supports_reply(service: InboxAnchorService) -> bool:
    supports = getattr(service.provider, "supports_outbound_email", None)
    return bool(callable(supports) and supports())


def _alias_slug(source: str, *, fallback: str = "mail", limit: int = 18) -> str:
    slug = "".join(character.lower() for character in source if character.isalnum())
    return (slug[:limit] or fallback).lower()


def _alias_nonce(length: int = 7) -> str:
    upper = 10**length
    lower = 10 ** (length - 1)
    return str(secrets.randbelow(upper - lower) + lower)


def _managed_alias_domain() -> str:
    return SETTINGS.alias_domain.strip().lower().lstrip("@")


def _managed_aliases_enabled() -> bool:
    return SETTINGS.alias_managed_enabled and bool(_managed_alias_domain())


def _managed_alias_inbound_ready() -> bool:
    return SETTINGS.alias_inbound_ready


def _managed_alias_blockers() -> list[str]:
    blockers: list[str] = []
    if not _managed_aliases_enabled():
        blockers.append(
            "Set INBOXANCHOR_ALIAS_MANAGED_ENABLED=true and "
            "INBOXANCHOR_ALIAS_DOMAIN to your alias domain."
        )
        return blockers
    if not _alias_resolver_secret_configured():
        blockers.append("Set INBOXANCHOR_ALIAS_RESOLVER_SECRET on the backend.")
    if not _managed_alias_resolver_base_url():
        blockers.append(
            "Set INBOXANCHOR_ALIAS_RESOLVER_BASE_URL to a public HTTPS URL for the InboxAnchor API."
        )
    elif not _managed_alias_public_backend_ready():
        blockers.append(
            "INBOXANCHOR_ALIAS_RESOLVER_BASE_URL must be a public HTTPS URL, "
            "not localhost or a private IP."
        )
    if not _managed_alias_inbound_ready():
        blockers.append(
            "Deploy the Cloudflare Email Routing worker, then set "
            "INBOXANCHOR_ALIAS_INBOUND_READY=true."
        )
    return blockers


def _managed_aliases_ready() -> bool:
    return _managed_aliases_enabled() and not _managed_alias_blockers()


def _plus_alias_fallback_enabled() -> bool:
    return SETTINGS.alias_allow_plus_fallback


def _alias_label_name(*, label: str = "", purpose: str = "") -> str:
    suffix_source = label.strip() or purpose.strip()
    if not suffix_source:
        return "InboxAnchor/Aliases"
    words = []
    current = []
    for character in suffix_source:
        if character.isalnum():
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    title = " ".join(word.capitalize() for word in words[:4]).strip()
    return f"InboxAnchor/Aliases/{title}" if title else "InboxAnchor/Aliases"


def _normalize_alias_address(value: str) -> str:
    return value.strip().lower()


def _generate_managed_alias(domain: str, *, label: str = "", purpose: str = "") -> str:
    slug = _alias_slug(label or purpose or "mail", fallback="mail", limit=16)
    return f"{slug}{_alias_nonce()}@{domain}"


def _generate_plus_alias(target_email: str, *, label: str = "", purpose: str = "") -> str:
    local_part, _, domain = target_email.partition("@")
    base_local = local_part.split("+", 1)[0]
    slug = _alias_slug(label or purpose or "mail", fallback="mail", limit=12)
    return f"{base_local}+ia-{slug}{_alias_nonce()}@{domain}"


def _provider_is_live_gmail(provider) -> bool:
    return getattr(provider, "provider_name", "") == "gmail" and bool(
        getattr(provider, "transport", None)
    )


def _configure_alias_inbox_routing(
    alias_address: str,
    *,
    label: str = "",
    purpose: str = "",
) -> str:
    gmail_service = InboxAnchorService(provider_name="gmail")
    provider = gmail_service.provider
    if not _provider_is_live_gmail(provider):
        return ""

    routing_label = _alias_label_name(label=label, purpose=purpose)
    configure = getattr(provider, "ensure_alias_routing", None)
    if not callable(configure):
        return ""

    try:
        configure(alias_address, label_name=routing_label, dry_run=False)
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        if "scope" in message.lower() or "gmail.settings.basic" in message.lower():
            raise HTTPException(
                status_code=400,
                detail=(
                    "Reconnect Gmail from Settings so InboxAnchor can request the Gmail "
                    "settings scope needed to auto-route alias mail."
                ),
            ) from exc
        raise HTTPException(
            status_code=502,
            detail=(
                "InboxAnchor created the alias, but could not install the Gmail routing "
                f"filter: {message}"
            ),
        ) from exc
    return routing_label


def _remove_alias_inbox_routing(alias_address: str) -> None:
    gmail_service = InboxAnchorService(provider_name="gmail")
    provider = gmail_service.provider
    if not _provider_is_live_gmail(provider):
        return
    remove = getattr(provider, "remove_alias_routing", None)
    if not callable(remove):
        return
    try:
        remove(alias_address, dry_run=False)
    except Exception:
        return


def _sync_active_alias_routing(aliases: list[EmailAlias]) -> None:
    for alias in aliases:
        if alias.status != "active":
            continue
        try:
            _configure_alias_inbox_routing(
                alias.alias_address,
                label=alias.label,
                purpose=alias.purpose,
            )
        except HTTPException:
            continue


def _alias_resolution_payload(alias: EmailAlias) -> dict:
    routing_label = _alias_label_name(label=alias.label, purpose=alias.purpose)
    return {
        "active": alias.status == "active",
        "alias_address": alias.alias_address,
        "forward_to": alias.target_email,
        "owner_email": alias.owner_email,
        "label_name": routing_label,
        "purpose": alias.purpose,
        "alias_type": alias.alias_type,
        "provider": alias.provider,
        "skip_inbox": True,
    }


def _frontend_email_payload(
    detail: dict,
    mailbox_email: Optional[dict] = None,
    *,
    reply_draft: Optional[str] = None,
    can_reply: Optional[bool] = None,
    reply_to_address: Optional[str] = None,
) -> dict:
    body_preview = normalize_email_body_text(detail.get("body_preview", ""))
    mailbox_body = normalize_email_body_text((mailbox_email or {}).get("body_full", ""))
    body_full = mailbox_body or body_preview
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
        "replyDraft": reply_draft,
        "canReply": can_reply,
        "replyToAddress": reply_to_address,
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


def _load_latest_classification_map(provider_name: str, email_ids: list[str]) -> dict[str, dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.get_latest_classification_map(provider_name, email_ids)


def _load_mailbox_classification_map(provider_name: str, email_ids: list[str]) -> dict[str, dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.get_mailbox_classification_map(provider_name, email_ids)


def _load_mailbox_classification_detail(provider_name: str, email_id: str) -> Optional[dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.get_mailbox_classification_detail(provider_name, email_id)


def _load_mailbox_classifications(
    provider_name: str,
    *,
    unread_only: Optional[bool] = None,
    q: Optional[str] = None,
    time_range: Optional[str] = None,
) -> dict[str, dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.list_mailbox_classifications(
            provider_name,
            unread_only=unread_only,
            q=q,
            time_range=normalize_time_range(time_range),
        )


def _load_mailbox_classification_stats(
    provider_name: str,
    *,
    unread_only: Optional[bool] = None,
    time_range: Optional[str] = None,
) -> dict:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.get_mailbox_classification_stats(
            provider_name,
            unread_only=unread_only,
            time_range=normalize_time_range(time_range),
        )


def _load_mailbox_workflow_counts(
    provider_name: str,
    *,
    unread_only: Optional[bool] = None,
    time_range: Optional[str] = None,
) -> dict:
    with session_scope() as session:
        repository = InboxRepository(session)
        recommendation_stats = repository.get_mailbox_recommendation_stats(
            provider_name,
            unread_only=unread_only,
            time_range=normalize_time_range(time_range),
        )
        action_item_count = repository.count_mailbox_action_items(
            provider_name,
            unread_only=unread_only,
            time_range=normalize_time_range(time_range),
        )
    recommendation_count = (
        int(recommendation_stats["safe_count"])
        + int(recommendation_stats["review_count"])
        + int(recommendation_stats["blocked_count"])
    )
    return {
        "action_item_count": int(action_item_count),
        "recommendation_count": recommendation_count,
    }


def _mailbox_workflow_unread_filter(unread_only: Optional[bool]) -> Optional[bool]:
    return True if unread_only is True else None


def _mailbox_email_to_model(mailbox_email: dict) -> EmailMessage:
    received_at = datetime.fromisoformat(str(mailbox_email["received_at"]))
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    return EmailMessage(
        id=str(mailbox_email["email_id"]),
        thread_id=str(mailbox_email.get("thread_id", "")),
        sender=str(mailbox_email.get("sender", "")),
        subject=str(mailbox_email.get("subject", "")),
        snippet=str(mailbox_email.get("snippet", "")),
        body_preview=str(mailbox_email.get("body_preview", "")),
        body_full=str(mailbox_email.get("body_full", "")),
        received_at=received_at,
        labels=[str(label) for label in mailbox_email.get("labels", [])],
        has_attachments=bool(mailbox_email.get("has_attachments")),
        unread=bool(mailbox_email.get("unread", True)),
    )


def _mailbox_classification_payload(
    provider_name: str,
    mailbox_email: dict,
    *,
    mailbox_classification: Optional[dict] = None,
    latest_classification: Optional[dict] = None,
) -> dict:
    if mailbox_classification and mailbox_classification.get("classification"):
        return mailbox_classification["classification"]
    if latest_classification and latest_classification.get("classification"):
        return latest_classification["classification"]

    email = _mailbox_email_to_model(mailbox_email)
    resolver = SenderIntelligenceResolver(provider_name)
    intelligence = resolver.resolve(email)
    classification = MAILBOX_PRIORITY_AGENT.prioritize(
        email,
        MAILBOX_CLASSIFIER.classify(
            email,
            intelligence=intelligence,
            allow_llm=False,
        ),
    )
    return classification.model_dump(mode="json")


def _mailbox_email_detail_payload(
    provider_name: str,
    mailbox_email: dict,
    *,
    mailbox_classification: Optional[dict] = None,
    latest_classification: Optional[dict] = None,
) -> dict:
    return {
        "email_id": mailbox_email["email_id"],
        "thread_id": mailbox_email.get("thread_id", ""),
        "sender": mailbox_email.get("sender", ""),
        "subject": mailbox_email.get("subject", ""),
        "snippet": mailbox_email.get("snippet", ""),
        "body_preview": mailbox_email.get("body_preview", ""),
        "received_at": mailbox_email.get("received_at"),
        "labels": mailbox_email.get("labels", []),
        "has_attachments": mailbox_email.get("has_attachments", False),
        "unread": mailbox_email.get("unread", True),
        "classification": _mailbox_classification_payload(
            provider_name,
            mailbox_email,
            mailbox_classification=mailbox_classification,
            latest_classification=latest_classification,
        ),
    }


def _maybe_seed_mailbox_cache(
    provider_name: str,
    *,
    time_range: Optional[str] = None,
) -> None:
    with session_scope() as session:
        repository = InboxRepository(session)
        overall_count = repository.count_mailbox_emails(provider_name)
    if overall_count == 0:
        settings = _get_workspace_settings()
        _sync_unread_working_set(
            provider_name,
            force_refresh=False,
            time_range=time_range or None,
            limit_override=min(settings.default_scan_limit, 50),
            batch_size_override=min(settings.default_batch_size, 50),
        )


def _sync_unread_working_set(
    provider_name: str,
    *,
    force_refresh: bool = True,
    time_range: Optional[str] = None,
    limit_override: Optional[int] = None,
    batch_size_override: Optional[int] = None,
    manage_active_job: bool = True,
    pre_registered_job: Optional[FrontendRunJob] = None,
) -> dict:
    del force_refresh
    normalized_time_range = normalize_time_range(time_range)
    scope_key = _scope_key(provider_name, normalized_time_range)
    service = _service_for_provider(provider_name)
    provider = getattr(service, "provider", None)
    settings = _get_workspace_settings()
    industrial_unread_mode = provider is not None and _use_industrial_unread_sync(
        provider,
        time_range=normalized_time_range,
    )
    scan_limit = None if industrial_unread_mode else (limit_override or settings.default_scan_limit)
    scan_batch_size = min(
        batch_size_override or settings.default_batch_size,
        100 if industrial_unread_mode else 250,
    )
    wait_job: Optional[FrontendRunJob] = None
    job = pre_registered_job
    owns_active_slot = manage_active_job or pre_registered_job is not None

    if manage_active_job:
        with FRONTEND_ACTIVE_RUNS_LOCK:
            active_job = FRONTEND_ACTIVE_RUNS.get(scope_key)
            if active_job is not None:
                wait_job = active_job
            else:
                job = FrontendRunJob(provider_name=provider_name)
                FRONTEND_ACTIVE_RUNS[scope_key] = job
    elif job is None:
        job = FrontendRunJob(provider_name=provider_name)

    if wait_job is not None:
        run_id, _ = _wait_for_frontend_job(
            wait_job,
            provider_name,
            time_range=normalized_time_range,
        )
        return {
            "provider": provider_name,
            "run_id": run_id,
            "count": 0,
            "processed_total": 0,
            "cached_count": _load_mailbox_cache_stats(
                provider_name,
                time_range=normalized_time_range,
            )["cached_count"],
        }
    assert job is not None

    seen_email_ids: list[str] = []
    processed_total = 0
    batch_count = 0
    latest_subject: Optional[str] = None
    cached_count = 0
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    workflow_counts = _load_mailbox_workflow_counts(
        provider_name,
        unread_only=True,
        time_range=normalized_time_range,
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "scan",
            "status": "running",
            "stage": "syncing_unread",
            "limit": _mailbox_progress_target(
                scan_limit,
                0,
                full_mailbox_mode=industrial_unread_mode,
                completed=False,
            ),
            "processed_emails": 0,
            "read_count": 0,
            "action_item_count": workflow_counts["action_item_count"],
            "recommendation_count": workflow_counts["recommendation_count"],
            "batch_count": 0,
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": cache_stats["hydrated_count"],
            "labeled_count": 0,
            "archived_count": 0,
            "marked_read_count": 0,
            "trashed_count": 0,
            "reply_sent_count": 0,
            "run_id": _get_cached_or_latest_run_id(provider_name, time_range=normalized_time_range),
            "error": None,
        },
        time_range=normalized_time_range,
    )

    try:
        if provider is None:
            result = service.engine.run(
                dry_run=True,
                limit=scan_limit,
                batch_size=scan_batch_size,
                include_body=False,
                extract_actions=False,
                draft_replies=False,
                confidence_threshold=settings.default_confidence_threshold,
                email_preview_limit=min(scan_limit, 120),
                recommendation_preview_limit=min(scan_limit, 120),
                workspace_policy=settings.policy,
                time_range=normalized_time_range,
            )
            processed_total = getattr(
                result,
                "scanned_emails",
                getattr(result, "total_emails", 0),
            )
            batch_count = getattr(result, "batch_count", 0)
            latest_subject = result.emails[0].subject if getattr(result, "emails", None) else None
            workflow_counts = {
                "action_item_count": sum(
                    len(items) for items in getattr(result, "action_items", {}).values()
                ),
                "recommendation_count": len(getattr(result, "recommendations", [])),
            }
            FRONTEND_RUN_CACHE[scope_key] = result.run_id
            cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
        else:
            batch_iterator = (
                provider.iter_all_unread_batches(
                    batch_size=scan_batch_size,
                    include_body=False,
                    time_range=normalized_time_range,
                )
                if industrial_unread_mode
                else provider.iter_unread_batches(
                    limit=scan_limit,
                    batch_size=scan_batch_size,
                    include_body=False,
                    time_range=normalized_time_range,
                )
            )
            for batch in batch_iterator:
                batch_count += 1
                with session_scope() as session:
                    repository = InboxRepository(session)
                    seen_email_ids.extend(_sync_mailbox_batch(repository, provider_name, batch))
                    processed_total += len(batch)
                    cache_stats = repository.get_mailbox_cache_stats(
                        provider_name,
                        time_range=normalized_time_range,
                    )
                    workflow_counts = _load_mailbox_workflow_counts(
                        provider_name,
                        unread_only=True,
                        time_range=normalized_time_range,
                    )
                cached_count = cache_stats["cached_count"]
                latest_subject = batch[0].subject if batch else latest_subject
                _update_frontend_progress(
                    provider_name,
                    {
                        "mode": "scan",
                        "status": "running",
                        "stage": "syncing_unread",
                        "limit": _mailbox_progress_target(
                            scan_limit,
                            processed_total,
                            full_mailbox_mode=industrial_unread_mode,
                            completed=False,
                        ),
                        "processed_emails": processed_total,
                        "read_count": processed_total,
                        "action_item_count": workflow_counts["action_item_count"],
                        "recommendation_count": workflow_counts["recommendation_count"],
                        "batch_count": batch_count,
                        "cached_count": cached_count,
                        "hydrated_count": cache_stats["hydrated_count"],
                        "oldest_cached_at": cache_stats["oldest_cached_at"],
                        "newest_cached_at": cache_stats["newest_cached_at"],
                        "latest_subject": latest_subject,
                        "error": None,
                    },
                    time_range=normalized_time_range,
                )
    except HTTPException:
        job.error = "InboxAnchor could not refresh the unread working set."
        job.event.set()
        if owns_active_slot:
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
        if owns_active_slot:
            with FRONTEND_ACTIVE_RUNS_LOCK:
                FRONTEND_ACTIVE_RUNS.pop(scope_key, None)
        raise HTTPException(status_code=502, detail=message) from exc

    fully_reconciled = provider is not None and (
        industrial_unread_mode or (scan_limit is not None and processed_total < scan_limit)
    )
    if fully_reconciled:
        with session_scope() as session:
            repository = InboxRepository(session)
            repository.reconcile_unread_working_set(
                provider_name,
                unread_email_ids=seen_email_ids,
                time_range=normalized_time_range,
            )
            cache_stats = repository.get_mailbox_cache_stats(
                provider_name,
                time_range=normalized_time_range,
            )
    else:
        cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    workflow_counts = _load_mailbox_workflow_counts(
        provider_name,
        unread_only=True,
        time_range=normalized_time_range,
    )

    latest_run_id = _get_cached_or_latest_run_id(provider_name, time_range=normalized_time_range)
    _update_frontend_progress(
        provider_name,
        {
            "mode": "scan",
            "status": "complete",
            "stage": "cache_ready",
            "limit": _mailbox_progress_target(
                scan_limit,
                processed_total,
                full_mailbox_mode=industrial_unread_mode,
                completed=True,
            ),
            "processed_emails": processed_total,
            "read_count": processed_total,
            "action_item_count": workflow_counts["action_item_count"],
            "recommendation_count": workflow_counts["recommendation_count"],
            "batch_count": batch_count,
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": cache_stats["hydrated_count"],
            "oldest_cached_at": cache_stats["oldest_cached_at"],
            "newest_cached_at": cache_stats["newest_cached_at"],
            "latest_subject": latest_subject,
            "run_id": latest_run_id,
            "error": None,
        },
        time_range=normalized_time_range,
    )
    job.run_id = latest_run_id
    job.event.set()
    if owns_active_slot:
        with FRONTEND_ACTIVE_RUNS_LOCK:
            FRONTEND_ACTIVE_RUNS.pop(scope_key, None)
    STREAM_HUB.emit(
        {
            "type": "scan_completed",
            "provider": provider_name,
            "run_id": latest_run_id,
            "processed_count": processed_total,
            "cached_count": cache_stats["cached_count"],
        }
    )
    return {
        "provider": provider_name,
        "run_id": latest_run_id,
        "count": processed_total,
        "processed_total": processed_total,
        "cached_count": cache_stats["cached_count"],
    }


def _start_unread_sync_job(
    provider_name: str,
    *,
    force_refresh: bool = True,
    time_range: Optional[str] = None,
) -> bool:
    normalized_time_range = normalize_time_range(time_range)
    scope_key = _scope_key(provider_name, normalized_time_range)
    job, wait_job = _claim_frontend_job(
        scope_key,
        provider_name=provider_name,
        mode="scan",
    )
    if wait_job is not None:
        return False
    assert job is not None

    settings = _get_workspace_settings()
    service = _service_for_provider(provider_name)
    provider = getattr(service, "provider", None)
    industrial_unread_mode = provider is not None and _use_industrial_unread_sync(
        provider,
        time_range=normalized_time_range,
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "scan",
            "status": "running",
            "stage": "queued",
            "limit": _mailbox_progress_target(
                None if industrial_unread_mode else settings.default_scan_limit,
                0,
                full_mailbox_mode=industrial_unread_mode,
                completed=False,
            ),
            "processed_emails": 0,
            "read_count": 0,
            "action_item_count": 0,
            "recommendation_count": 0,
            "batch_count": 0,
            "run_id": _get_cached_or_latest_run_id(
                provider_name,
                time_range=normalized_time_range,
            ),
            "error": None,
        },
        time_range=normalized_time_range,
    )

    def _runner() -> None:
        try:
            _sync_unread_working_set(
                provider_name,
                force_refresh=force_refresh,
                time_range=normalized_time_range,
                manage_active_job=False,
                pre_registered_job=job,
            )
        except HTTPException:
            return
        except Exception as exc:
            message = _provider_runtime_error_message(provider_name, exc)
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

    threading.Thread(
        target=_runner,
        name=f"inboxanchor-scan-{provider_name}-{normalized_time_range}",
        daemon=True,
    ).start()
    return True


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


def _load_unread_mailbox_preview(
    provider_name: str,
    *,
    time_range: Optional[str] = None,
    limit: int = 120,
) -> list[dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        return repository.list_mailbox_emails(
            provider_name,
            limit=limit,
            offset=0,
            unread_only=True,
            time_range=normalize_time_range(time_range),
        )


def _build_cache_digest(
    provider_name: str,
    *,
    time_range: Optional[str] = None,
    run_id: Optional[str] = None,
) -> dict:
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=time_range)
    preview = _load_unread_mailbox_preview(provider_name, time_range=time_range, limit=120)
    classification_stats = _load_mailbox_classification_stats(
        provider_name,
        unread_only=True,
        time_range=time_range,
    )
    summary = ""
    category_counts: dict[str, int] = dict(classification_stats.get("category_counts", {}))
    high_priority_ids: list[str] = list(classification_stats.get("high_priority_ids", []))
    if run_id:
        try:
            digest = _load_digest(run_id)
        except HTTPException:
            digest = None
        if digest:
            summary = digest["summary"]
            if not category_counts:
                category_counts = dict(digest.get("category_counts", {}))
            if not high_priority_ids:
                high_priority_ids = list(digest.get("high_priority_ids", []))

    if not summary:
        top_senders = []
        for item in preview:
            sender = str(item.get("sender", "")).strip()
            if sender and sender not in top_senders:
                top_senders.append(sender)
            if len(top_senders) >= 3:
                break
        if top_senders:
            summary = (
                f"{cache_stats['cached_unread_count']} unread emails are cached locally. "
                f"Recent senders: {', '.join(top_senders)}."
            )
        else:
            summary = (
                f"{cache_stats['cached_unread_count']} unread emails are cached locally "
                "and ready for review."
            )

    return {
        "total_unread": cache_stats["cached_unread_count"],
        "category_counts": category_counts,
        "high_priority_ids": high_priority_ids,
        "summary": summary,
    }


def _has_active_frontend_job(scope_key: str) -> bool:
    with FRONTEND_ACTIVE_RUNS_LOCK:
        job = FRONTEND_ACTIVE_RUNS.get(scope_key)
    return job is not None and not job.event.is_set()


def _active_frontend_job_is_stale(scope_key: str, job: FrontendRunJob) -> bool:
    if job.event.is_set():
        return True
    progress = FRONTEND_PROGRESS.get(scope_key)
    if not progress:
        return True
    if progress.get("status") != "running":
        return True
    updated_at = progress.get("updated_at")
    if not updated_at:
        return False
    try:
        updated = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - updated).total_seconds() > 300


def _claim_frontend_job(
    scope_key: str,
    *,
    provider_name: str,
    mode: str,
) -> tuple[Optional[FrontendRunJob], Optional[FrontendRunJob]]:
    with FRONTEND_ACTIVE_RUNS_LOCK:
        active_job = FRONTEND_ACTIVE_RUNS.get(scope_key)
        if active_job is not None:
            if not _active_frontend_job_is_stale(scope_key, active_job):
                return None, active_job
            FRONTEND_ACTIVE_RUNS.pop(scope_key, None)
        job = FrontendRunJob(provider_name=provider_name, mode=mode)
        FRONTEND_ACTIVE_RUNS[scope_key] = job
        return job, None


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


def _synthesized_complete_progress(
    provider_name: str,
    run_id: str,
    *,
    time_range: Optional[str] = None,
    previous: Optional[dict] = None,
) -> dict:
    overview = _build_ops_overview(provider_name, run_id, time_range=time_range)
    workflow_counts = _load_mailbox_workflow_counts(
        provider_name,
        unread_only=True,
        time_range=overview["timeRange"],
    )
    previous = previous or {}
    return {
        "provider": provider_name,
        "time_range": overview["timeRange"],
        "time_range_label": overview["timeRangeLabel"],
        "mode": previous.get("mode", "scan"),
        "status": "complete",
        "stage": "ready",
        "target_count": int(overview["unreadCount"]),
        "processed_count": int(overview["unreadCount"]),
        "read_count": int(overview["unreadCount"]),
        "action_item_count": int(workflow_counts["action_item_count"]),
        "recommendation_count": int(workflow_counts["recommendation_count"]),
        "batch_count": int(previous.get("batch_count", 0)),
        "cached_count": int(overview["cachedEmailsCount"]),
        "hydrated_count": int(overview["hydratedEmailsCount"]),
        "labeled_count": int(previous.get("labeled_count", 0)),
        "labels_removed_count": int(previous.get("labels_removed_count", 0)),
        "archived_count": int(previous.get("archived_count", 0)),
        "marked_read_count": int(previous.get("marked_read_count", 0)),
        "trashed_count": int(previous.get("trashed_count", 0)),
        "reply_sent_count": int(previous.get("reply_sent_count", 0)),
        "oldest_cached_at": overview["oldestCachedAt"],
        "newest_cached_at": overview["newestCachedAt"],
        "latest_subject": previous.get("latest_subject"),
        "latest_action": previous.get("latest_action"),
        "resume_offset": int(previous.get("resume_offset", 0)),
        "remaining_count": 0,
        "completed": True,
        "run_id": run_id,
        "error": None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _should_reconcile_stale_scan_progress(progress: dict, scope_key: str) -> bool:
    if progress.get("status") != "running":
        return False
    if progress.get("mode") not in {None, "", "scan"}:
        return False
    if progress.get("run_id"):
        return False
    if _has_active_frontend_job(scope_key):
        return False
    processed_count = int(progress.get("processed_count") or 0)
    read_count = int(progress.get("read_count") or 0)
    return processed_count == 0 and read_count == 0


def _load_action_items(run_id: str, email_id: str) -> list[dict]:
    with session_scope() as session:
        return InboxRepository(session).list_action_items_for_email(run_id, email_id)


def _mailbox_recommendation_sort_key(detail: dict) -> tuple[int, int, float, str]:
    status_order = {
        "blocked": 0,
        "requires_approval": 1,
        "safe": 2,
    }
    priority_order = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    classification = detail["classification"]
    return (
        status_order.get(str(detail.get("status", "")), 3),
        priority_order.get(str(classification.get("priority", "")), 4),
        -float(detail.get("confidence", 0.0)),
        str(detail.get("received_at", "")),
    )


def _mailbox_action_items_for_email(
    email: EmailMessage,
    classification: EmailClassification,
) -> list[dict]:
    items = MAILBOX_ACTION_EXTRACTOR.extract(
        email,
        classification=classification,
        allow_llm=False,
    )
    return [item.model_dump(mode="json") for item in items]


def _mailbox_recommendation_for_email(
    email: EmailMessage,
    classification: EmailClassification,
    *,
    policy: Optional[object] = None,
) -> EmailRecommendation:
    workspace_policy = policy or _get_workspace_settings().policy
    return MAILBOX_SAFETY_VERIFIER.verify(
        email,
        classification,
        MAILBOX_RULES_ENGINE.recommend(
            email,
            classification,
            now=datetime.now(timezone.utc),
            policy=workspace_policy,
        ),
        policy=workspace_policy,
    )


def _mailbox_recommendation_detail(
    provider_name: str,
    mailbox_email: dict,
    *,
    mailbox_classification: Optional[dict] = None,
    latest_classification: Optional[dict] = None,
    policy: Optional[object] = None,
) -> dict:
    detail = _mailbox_email_detail_payload(
        provider_name,
        mailbox_email,
        mailbox_classification=mailbox_classification,
        latest_classification=latest_classification,
    )
    email = _mailbox_email_to_model(mailbox_email)
    classification = EmailClassification.model_validate(detail["classification"])
    recommendation = _mailbox_recommendation_for_email(
        email,
        classification,
        policy=policy,
    )
    detail.update(recommendation.model_dump(mode="json"))
    return detail


def _classify_mailbox_email(
    provider_name: str,
    mailbox_email: dict,
    *,
    resolver: Optional[SenderIntelligenceResolver] = None,
) -> tuple[EmailMessage, EmailClassification]:
    email = _mailbox_email_to_model(mailbox_email)
    local_resolver = resolver or SenderIntelligenceResolver(provider_name)
    intelligence = local_resolver.resolve(email)
    classification = MAILBOX_PRIORITY_AGENT.prioritize(
        email,
        MAILBOX_CLASSIFIER.classify(
            email,
            intelligence=intelligence,
            allow_llm=False,
        ),
    )
    local_resolver.observe(email, context=intelligence)
    return email, classification


def _persist_mailbox_workflow_enrichment(
    repository: InboxRepository,
    provider_name: str,
    mailbox_email: dict,
    *,
    mailbox_classification: Optional[dict] = None,
    latest_classification: Optional[dict] = None,
    policy: Optional[object] = None,
    force_refresh: bool = False,
    resolver: Optional[SenderIntelligenceResolver] = None,
) -> tuple[dict, list[dict]]:
    effective_classification = mailbox_classification if not force_refresh else None
    if effective_classification is None and not force_refresh:
        effective_classification = latest_classification

    if effective_classification and effective_classification.get("classification"):
        email = _mailbox_email_to_model(mailbox_email)
        classification = EmailClassification.model_validate(
            effective_classification["classification"]
        )
    else:
        email, classification = _classify_mailbox_email(
            provider_name,
            mailbox_email,
            resolver=resolver,
        )
        effective_classification = repository.upsert_mailbox_classification(
            provider_name,
            email.id,
            classification,
            source="heuristic",
        )

    detail = _mailbox_email_detail_payload(
        provider_name,
        mailbox_email,
        mailbox_classification=effective_classification,
    )
    recommendation = _mailbox_recommendation_for_email(
        email,
        classification,
        policy=policy,
    )
    detail.update(recommendation.model_dump(mode="json"))
    items = [
        EmailActionItem.model_validate(item)
        for item in _mailbox_action_items_for_email(email, classification)
    ]
    repository.replace_mailbox_action_items(
        provider_name,
        email.id,
        items,
        source="heuristic",
    )
    repository.upsert_mailbox_recommendation(
        provider_name,
        email.id,
        EmailRecommendation.model_validate(
            {
                "email_id": email.id,
                "recommended_action": detail["recommended_action"],
                "reason": detail["reason"],
                "confidence": detail["confidence"],
                "status": detail["status"],
                "requires_approval": detail["requires_approval"],
                "blocked_reason": detail.get("blocked_reason"),
                "proposed_labels": detail.get("proposed_labels", []),
            }
        ),
        source="heuristic",
    )
    return detail, [item.model_dump(mode="json") for item in items]


def _sync_mailbox_batch(
    repository: InboxRepository,
    provider_name: str,
    batch: list[EmailMessage],
) -> list[str]:
    email_ids: list[str] = []
    for email in batch:
        repository.upsert_mailbox_email(provider_name, email)
        email_ids.append(email.id)
    repository.clear_mailbox_workflow_enrichment(provider_name, email_ids)
    return email_ids


def _enrich_mailbox_cache(
    provider_name: str,
    *,
    unread_only: Optional[bool] = True,
    time_range: Optional[str] = None,
    force_refresh: bool = False,
    page_size: int = 250,
) -> dict:
    normalized_time_range = normalize_time_range(time_range)
    policy = _get_workspace_settings().policy
    resolver = SenderIntelligenceResolver(provider_name)
    offset = 0
    processed_count = 0
    latest_subject: Optional[str] = None
    workflow_counts = {
        "action_item_count": 0,
        "recommendation_count": 0,
    }

    while True:
        with session_scope() as session:
            repository = InboxRepository(session)
            page = repository.list_mailbox_emails(
                provider_name,
                limit=page_size,
                offset=offset,
                unread_only=unread_only,
                time_range=normalized_time_range,
            )
            if not page:
                break
            email_ids = [item["email_id"] for item in page]
            mailbox_classifications = (
                {}
                if force_refresh
                else repository.get_mailbox_classification_map(provider_name, email_ids)
            )
            latest_classifications = (
                {}
                if force_refresh
                else repository.get_latest_classification_map(
                    provider_name,
                    [email_id for email_id in email_ids if email_id not in mailbox_classifications],
                )
            )
            for item in page:
                _persist_mailbox_workflow_enrichment(
                    repository,
                    provider_name,
                    item,
                    mailbox_classification=mailbox_classifications.get(item["email_id"]),
                    latest_classification=latest_classifications.get(item["email_id"]),
                    policy=policy,
                    force_refresh=force_refresh,
                    resolver=resolver,
                )
                processed_count += 1
                latest_subject = item.get("subject") or latest_subject
            recommendation_stats = repository.get_mailbox_recommendation_stats(
                provider_name,
                unread_only=unread_only,
                time_range=normalized_time_range,
            )
            workflow_counts = {
                "action_item_count": repository.count_mailbox_action_items(
                    provider_name,
                    unread_only=unread_only,
                    time_range=normalized_time_range,
                ),
                "recommendation_count": (
                    int(recommendation_stats["safe_count"])
                    + int(recommendation_stats["review_count"])
                    + int(recommendation_stats["blocked_count"])
                ),
            }
        if len(page) < page_size:
            break
        offset += len(page)

    return {
        "count": processed_count,
        "latest_subject": latest_subject,
        "action_item_count": workflow_counts["action_item_count"],
        "recommendation_count": workflow_counts["recommendation_count"],
    }


def _load_mailbox_recommendation_details(
    provider_name: str,
    *,
    time_range: Optional[str] = None,
    email_id: str = "",
    unread_only: Optional[bool] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    normalized_time_range = normalize_time_range(time_range)
    policy = _get_workspace_settings().policy
    with session_scope() as session:
        repository = InboxRepository(session)
        if email_id:
            mailbox_email = repository.get_mailbox_email(provider_name, email_id)
            if mailbox_email is None:
                return []
            recommendation = repository.get_mailbox_recommendation_detail(provider_name, email_id)
            mailbox_classification = repository.get_mailbox_classification_detail(
                provider_name,
                email_id,
            )
            latest_classification = repository.get_latest_classification_detail(
                provider_name,
                email_id,
            )
            if recommendation is None:
                detail, _ = _persist_mailbox_workflow_enrichment(
                    repository,
                    provider_name,
                    mailbox_email,
                    mailbox_classification=mailbox_classification,
                    latest_classification=latest_classification,
                    policy=policy,
                )
                return [detail]
            detail = _mailbox_email_detail_payload(
                provider_name,
                mailbox_email,
                mailbox_classification=mailbox_classification,
                latest_classification=latest_classification,
            )
            detail.update(recommendation)
            return [detail]

        total = repository.count_mailbox_emails(
            provider_name,
            unread_only=unread_only,
            time_range=normalized_time_range,
        )
        page = repository.list_mailbox_emails(
            provider_name,
            limit=max(limit or total, 1),
            offset=0,
            unread_only=unread_only,
            time_range=normalized_time_range,
        )
        email_ids = [item["email_id"] for item in page]
        mailbox_classifications = repository.get_mailbox_classification_map(
            provider_name,
            email_ids,
        )
        mailbox_recommendations = repository.get_mailbox_recommendation_map(
            provider_name,
            email_ids,
        )
        latest_classifications = repository.get_latest_classification_map(
            provider_name,
            [email_id for email_id in email_ids if email_id not in mailbox_classifications],
        )
        details: list[dict] = []
        for item in page:
            mailbox_classification = mailbox_classifications.get(item["email_id"])
            latest_classification = latest_classifications.get(item["email_id"])
            recommendation = mailbox_recommendations.get(item["email_id"])
            if recommendation is None:
                detail, _ = _persist_mailbox_workflow_enrichment(
                    repository,
                    provider_name,
                    item,
                    mailbox_classification=mailbox_classification,
                    latest_classification=latest_classification,
                    policy=policy,
                )
            else:
                detail = _mailbox_email_detail_payload(
                    provider_name,
                    item,
                    mailbox_classification=mailbox_classification,
                    latest_classification=latest_classification,
                )
                detail.update(recommendation)
            details.append(detail)
    details.sort(key=_mailbox_recommendation_sort_key)
    return details[:limit] if limit else details


def _iter_mailbox_recommendation_details(
    provider_name: str,
    *,
    unread_only: Optional[bool] = None,
    time_range: Optional[str] = None,
    page_size: int = 250,
):
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=time_range)
    if unread_only and cache_stats["cached_unread_count"] == 0:
        for detail in _load_mailbox_recommendation_details(
            provider_name,
            time_range=time_range,
            unread_only=unread_only,
        ):
            yield detail
        return
    normalized_time_range = normalize_time_range(time_range)
    policy = _get_workspace_settings().policy
    offset = 0
    while True:
        with session_scope() as session:
            repository = InboxRepository(session)
            page = repository.list_mailbox_emails(
                provider_name,
                limit=page_size,
                offset=offset,
                unread_only=unread_only,
                time_range=normalized_time_range,
            )
            if not page:
                return
            email_ids = [item["email_id"] for item in page]
            mailbox_classifications = repository.get_mailbox_classification_map(
                provider_name,
                email_ids,
            )
            mailbox_recommendations = repository.get_mailbox_recommendation_map(
                provider_name,
                email_ids,
            )
            latest_classifications = repository.get_latest_classification_map(
                provider_name,
                [email_id for email_id in email_ids if email_id not in mailbox_classifications],
            )
            details: list[dict] = []
            for item in page:
                mailbox_classification = mailbox_classifications.get(item["email_id"])
                latest_classification = latest_classifications.get(item["email_id"])
                recommendation = mailbox_recommendations.get(item["email_id"])
                if recommendation is None:
                    detail, _ = _persist_mailbox_workflow_enrichment(
                        repository,
                        provider_name,
                        item,
                        mailbox_classification=mailbox_classification,
                        latest_classification=latest_classification,
                        policy=policy,
                    )
                else:
                    detail = _mailbox_email_detail_payload(
                        provider_name,
                        item,
                        mailbox_classification=mailbox_classification,
                        latest_classification=latest_classification,
                    )
                    detail.update(recommendation)
                details.append(detail)
        details.sort(key=_mailbox_recommendation_sort_key)
        for detail in details:
            yield detail
        if len(page) < page_size:
            return
        offset += len(page)


def _load_mailbox_action_items(provider_name: str, email_id: str) -> list[dict]:
    with session_scope() as session:
        repository = InboxRepository(session)
        mailbox_email = repository.get_mailbox_email(provider_name, email_id)
        mailbox_classification = repository.get_mailbox_classification_detail(
            provider_name,
            email_id,
        )
        latest_classification = repository.get_latest_classification_detail(provider_name, email_id)
        items = repository.get_mailbox_action_items(provider_name, email_id)
    if mailbox_email is None:
        return []
    if items:
        return items
    with session_scope() as session:
        repository = InboxRepository(session)
        _detail, persisted_items = _persist_mailbox_workflow_enrichment(
            repository,
            provider_name,
            mailbox_email,
            mailbox_classification=mailbox_classification,
            latest_classification=latest_classification,
            policy=_get_workspace_settings().policy,
        )
    return persisted_items


def _find_mailbox_recommendation_detail(
    provider_name: str,
    email_id: str,
    *,
    time_range: Optional[str] = None,
) -> dict:
    details = _load_mailbox_recommendation_details(
        provider_name,
        time_range=time_range,
        email_id=email_id,
    )
    if not details:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return details[0]


def _find_recommendation_detail(run_id: str, email_id: str) -> dict:
    with session_scope() as session:
        detail = InboxRepository(session).get_run_recommendation_detail(run_id, email_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return detail


def _labels_to_remove_for_email(detail: dict) -> list[str]:
    suggested = _recommended_labels_for_email(detail)
    existing = [str(label) for label in detail.get("labels", [])]
    return select_inboxanchor_labels(existing, suggested)


def _list_provider_cleanup_labels(provider_name: str) -> list[str]:
    service = _service_for_provider(provider_name)
    provider = service.provider
    try:
        labels = provider.list_labels()
    except Exception:
        return []
    return select_provider_cleanup_labels([str(label) for label in labels])


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
        repository = InboxRepository(session)
        repository.add_audit_entry(audit_entry)
        repository.update_mailbox_email_state(
            provider_name,
            email_id,
            unread=False if action in {"mark_read", "archive", "trash"} else None,
            labels_to_add=labels or None,
        )
    return {
        "emailId": email_id,
        "action": action,
        "finalAction": final_action,
        "labelsApplied": labels,
    }


def _remove_provider_labels(
    provider_name: str,
    email_id: str,
    labels: list[str],
    *,
    reason: str,
    confidence: float,
    approved_by_user: bool,
    safety_status: str,
) -> dict:
    if not labels:
        return {
            "emailId": email_id,
            "action": "remove_labels",
            "finalAction": "labels_unchanged",
            "labelsRemoved": [],
        }

    service = _service_for_provider(provider_name)
    provider = service.provider
    try:
        provider.remove_labels([email_id], labels, dry_run=False)
    except HTTPException:
        raise
    except Exception as exc:
        _raise_provider_runtime_error(provider_name, exc)

    _record_label_removal_decision(
        email_id,
        reason=reason,
        confidence=confidence,
        approved_by_user=approved_by_user,
        safety_status=safety_status,
    )
    return {
        "emailId": email_id,
        "action": "remove_labels",
        "finalAction": "labels_removed",
        "labelsRemoved": labels,
    }


def _delete_provider_labels(
    provider_name: str,
    labels: list[str],
) -> dict:
    deduped = dedupe_labels(labels)
    if not deduped:
        return {
            "provider": provider_name,
            "action": "delete_labels",
            "deletedLabels": [],
            "deletedCount": 0,
            "details": "No InboxAnchor label definitions needed pruning.",
        }

    service = _service_for_provider(provider_name)
    provider = service.provider
    try:
        result = provider.delete_labels(deduped, dry_run=False)
    except Exception as exc:
        _raise_provider_runtime_error(provider_name, exc)

    deleted_count = len(deduped) if result.executed else 0
    return {
        "provider": provider_name,
        "action": "delete_labels",
        "deletedLabels": deduped if result.executed else [],
        "deletedCount": deleted_count,
        "details": result.details,
    }


def _record_label_removal_decision(
    email_id: str,
    *,
    reason: str,
    confidence: float,
    approved_by_user: bool,
    safety_status: str,
) -> None:
    decision = AutomationDecision(
        email_id=email_id,
        proposed_action="remove_labels",
        final_action="labels_removed",
        approved_by_user=approved_by_user,
        reason=reason,
        confidence=confidence,
        safety_verifier_status=safety_status,
    )
    audit_logger = AuditLogger()
    audit_entry = audit_logger.create_entry(decision)
    with session_scope() as session:
        InboxRepository(session).add_audit_entry(audit_entry)


def _build_ops_overview(
    provider_name: str,
    run_id: Optional[str],
    *,
    time_range: Optional[str] = None,
) -> dict:
    normalized_time_range = normalize_time_range(time_range)
    settings = _get_workspace_settings()
    digest = _build_cache_digest(provider_name, time_range=normalized_time_range, run_id=run_id)
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    connection = InboxAnchorService().load_provider_connection(provider_name)
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    sync_state = _load_mailbox_sync_state(provider_name, time_range=normalized_time_range)
    processed_total = max(
        cache_stats["cached_count"],
        int(sync_state.get("processed_count") or 0) if sync_state else 0,
    )
    historical_target = max(settings.default_scan_limit * 4, 5000)
    full_mailbox_mode = bool(sync_state.get("full_mailbox")) if sync_state else False
    if full_mailbox_mode:
        mailbox_target = processed_total if sync_state and sync_state.get("completed") else 0
    else:
        mailbox_target = (
            max(historical_target, int(sync_state.get("target_count") or 0))
            if sync_state
            else historical_target
        )
    resume_offset = min(
        max(
            int(sync_state.get("next_offset") or 0),
            processed_total,
        )
        if sync_state
        else processed_total,
        mailbox_target or processed_total,
    )
    mailbox_memory = {
        "targetCount": mailbox_target,
        "processedTotal": processed_total,
        "resumeOffset": resume_offset,
        "remainingCount": _mailbox_limit_remaining(
            None if full_mailbox_mode and mailbox_target == 0 else mailbox_target,
            resume_offset,
        ),
        "completed": bool(sync_state.get("completed")) if sync_state else False,
        "fullMailboxMode": full_mailbox_mode,
        "includeBody": bool(sync_state.get("include_body")) if sync_state else False,
        "unreadOnly": bool(sync_state.get("unread_only")) if sync_state else False,
        "lastBackfillAt": sync_state.get("updated_at") if sync_state else None,
    }
    with session_scope() as session:
        repository = InboxRepository(session)
        recommendation_stats = repository.get_mailbox_recommendation_stats(
            provider_name,
            unread_only=True,
            time_range=normalized_time_range,
        )
        classification_stats = repository.get_mailbox_classification_stats(
            provider_name,
            unread_only=True,
            time_range=normalized_time_range,
        )
        safe_count = recommendation_stats["safe_count"]
        review_count = recommendation_stats["review_count"]
        blocked_count = recommendation_stats["blocked_count"]
        auto_label_candidates = recommendation_stats["auto_label_candidates"]
        high_priority_count = len(classification_stats["high_priority_ids"])
        attachment_count = repository.count_mailbox_emails(
            provider_name,
            unread_only=True,
            time_range=normalized_time_range,
            has_attachments=True,
        )

    return {
        "provider": provider_name,
        "timeRange": normalized_time_range,
        "timeRangeLabel": time_range_label(normalized_time_range),
        "timeRangeOptions": available_time_ranges(),
        "runId": run_id or f"sync::{provider_name}::{normalized_time_range}",
        "unreadCount": cache_stats["cached_unread_count"],
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
                    (
                        f"Scans the full unread working set in "
                        f"{time_range_label(normalized_time_range).lower()}."
                    )
                    if normalized_time_range == ALL_TIME_RANGE and provider_name == "gmail"
                    else (
                        f"Scans up to {settings.default_scan_limit} unread emails in "
                        f"{time_range_label(normalized_time_range).lower()}."
                    )
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
                    (
                        f"Cache the full mailbox history for "
                        f"{time_range_label(normalized_time_range).lower()} so search, "
                        "hydration, and future syncs have more context."
                    )
                    if full_mailbox_mode
                    else (
                        f"Cache up to {mailbox_target} historical emails for "
                        f"{time_range_label(normalized_time_range).lower()} so search, "
                        "hydration, and future syncs have more context."
                    )
                ),
            },
            {
                "slug": "classify-cache",
                "label": "Prepare unread decisions",
                "description": (
                    "Rebuild sender-aware classifications, action items, and safety "
                    "recommendations from the cached unread working set."
                ),
                "impact": (
                    f"{cache_stats['cached_unread_count']} unread cached emails in "
                    f"{time_range_label(normalized_time_range).lower()} can be prepared for "
                    "labeling and cleanup without re-reading the live provider."
                ),
            },
            {
                "slug": "auto-label",
                "label": "Auto-label unread mail",
                "description": "Apply one clean InboxAnchor label per unread email.",
                "impact": (
                    (
                        f"{auto_label_candidates} unread emails in "
                        f"{time_range_label(normalized_time_range).lower()} already have prepared "
                        "recommendations that can be labeled right now."
                    )
                    if auto_label_candidates
                    else (
                        f"Prepare unread decisions first to rebuild label-ready recommendations "
                        f"for {cache_stats['cached_unread_count']} cached unread emails in "
                        f"{time_range_label(normalized_time_range).lower()}."
                    )
                ),
            },
            {
                "slug": "clean-labels",
                "label": "Reset InboxAnchor labels",
                "description": "Remove only InboxAnchor-generated labels from the mailbox window.",
                "impact": (
                    f"Useful when {time_range_label(normalized_time_range).lower()} needs a clean "
                    "label reset without touching the underlying emails."
                ),
            },
            {
                "slug": "industrial-read",
                "label": "Industrial mark as read",
                "description": (
                    "Mark the full cached unread working set as read in provider-sized "
                    "batches without waiting on recommendations or labels."
                ),
                "impact": (
                    f"Marks {cache_stats['cached_unread_count']} unread emails as read in "
                    f"{time_range_label(normalized_time_range).lower()}."
                ),
            },
            {
                "slug": "safe-cleanup",
                "label": "Run safe cleanup",
                "description": "Apply only low-risk mark-read and archive actions.",
                "impact": (
                    (
                        f"{safe_count} prepared recommendations in "
                        f"{time_range_label(normalized_time_range).lower()} are safe to execute "
                        "immediately."
                    )
                    if safe_count
                    else (
                        "Prepare unread decisions first so InboxAnchor can rebuild the current "
                        "safe cleanup set from cache."
                    )
                ),
            },
            {
                "slug": "full-anchor",
                "label": "Mailbox upgrade sweep",
                "description": (
                    "Prepare unread decisions, label the set, then run safe cleanup on the "
                    "same unread working set."
                ),
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
    unread_only: Optional[bool] = Query(default=None),
    limit: int = Query(default=25, ge=1, le=250),
    offset: int = Query(default=0, ge=0),
):
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    mailbox_unread_only = True if unread_only is not False else False
    with session_scope() as session:
        repository = InboxRepository(session)
        total = repository.count_mailbox_emails(
            provider_name,
            unread_only=mailbox_unread_only,
            q=q or None,
            time_range=time_range or None,
            priority=priority or None,
            category=category or None,
        )
        page = repository.list_mailbox_emails(
            provider_name,
            limit=limit,
            offset=offset,
            unread_only=mailbox_unread_only,
            q=q or None,
            time_range=time_range or None,
            priority=priority or None,
            category=category or None,
        )
    mailbox_classifications = _load_mailbox_classification_map(
        provider_name,
        [item["email_id"] for item in page],
    )
    return {
        "emails": [
            _frontend_email_payload(
                _mailbox_email_detail_payload(
                    provider_name,
                    item,
                    mailbox_classification=mailbox_classifications.get(item["email_id"]),
                ),
                item,
            )
            for item in page
        ],
        "total": total,
    }


@router.get("/emails/{email_id}")
def frontend_email(email_id: str, time_range: str = ""):
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    service = _service_for_provider(provider_name)
    with session_scope() as session:
        repository = InboxRepository(session)
        mailbox_email = repository.get_mailbox_email(provider_name, email_id)
        mailbox_classification = repository.get_mailbox_classification_detail(
            provider_name,
            email_id,
        )
        latest_classification = repository.get_latest_classification_detail(provider_name, email_id)
        latest_run_id = repository.get_latest_run_id(provider_name)
    if mailbox_email is None:
        run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
        with session_scope() as session:
            detail = InboxRepository(session).get_run_email_detail(run_id, email_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Email not found")
        mailbox_map = _load_mailbox_email_map(provider_name, [email_id])
        mailbox_email = mailbox_map.get(email_id)
        latest_run_id = run_id
    else:
        detail = _mailbox_email_detail_payload(
            provider_name,
            mailbox_email,
            mailbox_classification=mailbox_classification,
            latest_classification=latest_classification,
        )
    mailbox_email = _hydrate_mailbox_email_if_needed(
        provider_name,
        email_id,
        detail,
        mailbox_email,
    )
    return _frontend_email_payload(
        detail,
        mailbox_email,
        reply_draft=_reply_draft_for_email(latest_run_id, email_id) if latest_run_id else None,
        can_reply=_provider_supports_reply(service),
        reply_to_address=_reply_target_for_detail(detail),
    )


@router.get("/classifications")
def frontend_classifications(time_range: str = ""):
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    normalized_time_range = normalize_time_range(time_range or None)
    classifications = _load_mailbox_classifications(
        provider_name,
        unread_only=True,
        time_range=normalized_time_range,
    )
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    if (
        cache_stats["cached_unread_count"]
        and len(classifications) < cache_stats["cached_unread_count"]
    ):
        _enrich_mailbox_cache(
            provider_name,
            unread_only=True,
            time_range=normalized_time_range,
            force_refresh=False,
        )
        classifications = _load_mailbox_classifications(
            provider_name,
            unread_only=True,
            time_range=normalized_time_range,
        )
    return {email_id: payload["classification"] for email_id, payload in classifications.items()}


@router.get("/recommendations")
def frontend_recommendations(email_id: str = "", time_range: str = ""):
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    preview_limit = _get_workspace_settings().default_recommendation_preview_limit
    if email_id:
        details = _load_mailbox_recommendation_details(
            provider_name,
            time_range=time_range or None,
            email_id=email_id,
            unread_only=None,
        )
    else:
        details = _load_mailbox_recommendation_details(
            provider_name,
            time_range=time_range or None,
            unread_only=True,
            limit=preview_limit,
        )
    return [
        _frontend_recommendation_payload(item, blocked=item["email_id"] in blocked)
        for item in details
    ]


@router.get("/emails/{email_id}/actions")
def frontend_action_items(email_id: str, time_range: str = ""):
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    with session_scope() as session:
        mailbox_email = InboxRepository(session).get_mailbox_email(provider_name, email_id)
    if mailbox_email is not None:
        items = _load_mailbox_action_items(provider_name, email_id)
    else:
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


@router.post("/emails/{email_id}/reply")
def frontend_send_reply(
    email_id: str,
    payload: FrontendReplySendRequest,
    authorization: Optional[str] = Header(default=None),
    time_range: str = "",
):
    actor_email = _require_actor_email(authorization)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Reply body cannot be empty.")

    run_id, provider_name = _ensure_frontend_run(time_range=time_range or None)
    service = _service_for_provider(provider_name)
    if not _provider_supports_reply(service):
        raise HTTPException(
            status_code=400,
            detail=(
                "This provider can be cleaned and labeled from InboxAnchor, but in-app "
                "reply sending is only available on supported providers like Gmail right now."
            ),
        )

    with session_scope() as session:
        detail = InboxRepository(session).get_run_email_detail(run_id, email_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Email not found")

    try:
        result = service.provider.send_reply(email_id, body, dry_run=False)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        _raise_provider_runtime_error(provider_name, exc)

    decision = AutomationDecision(
        email_id=email_id,
        proposed_action="reply",
        final_action="reply_sent",
        approved_by_user=True,
        reason="Reply sent manually from InboxAnchor.",
        confidence=1.0,
        safety_verifier_status=SafetyStatus.allowed,
    )
    with session_scope() as session:
        InboxRepository(session).add_audit_entry(AuditLogger().create_entry(decision))

    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "complete",
            "stage": "reply_sent",
            "limit": 1,
            "processed_emails": 1,
            "read_count": 1,
            "reply_sent_count": 1,
            "latest_subject": detail["subject"],
            "latest_action": "reply",
            "error": None,
        },
        time_range=time_range or None,
    )
    STREAM_HUB.emit(
        {
            "type": "reply_sent",
            "provider": provider_name,
            "email_id": email_id,
            "actor": actor_email,
        }
    )
    return {
        "ok": True,
        "emailId": email_id,
        "provider": provider_name,
        "toAddress": _reply_target_for_detail(detail),
        "details": result.details,
    }


@router.get("/aliases")
def frontend_list_aliases(
    authorization: Optional[str] = Header(default=None),
    status: str = "",
):
    actor_email = _require_actor_email(authorization)
    with session_scope() as session:
        aliases = InboxRepository(session).list_email_aliases(
            owner_email=actor_email,
            status=status or None,
        )
    _sync_active_alias_routing(aliases)
    return {
        "items": [alias.model_dump(mode="json") for alias in aliases],
        "count": len(aliases),
        "mode": "managed" if _managed_aliases_enabled() else "plus",
        "domain": _managed_alias_domain() or None,
        "managed_enabled": _managed_aliases_enabled(),
        "managed_ready": _managed_aliases_ready(),
        "managed_resolver_configured": _alias_resolver_secret_configured(),
        "managed_resolver_base_url": _managed_alias_resolver_base_url() or None,
        "managed_public_backend_ready": _managed_alias_public_backend_ready(),
        "managed_inbound_ready": _managed_alias_inbound_ready(),
        "managed_blockers": _managed_alias_blockers(),
        "plus_fallback_enabled": _plus_alias_fallback_enabled(),
    }


@router.post("/aliases/generate")
def frontend_generate_alias(
    payload: FrontendAliasGenerateRequest,
    authorization: Optional[str] = Header(default=None),
):
    actor_email = _require_actor_email(authorization)
    connection = InboxAnchorService().load_provider_connection("gmail")
    target_email = (connection.account_hint or actor_email).strip().lower()
    if "@" not in target_email:
        raise HTTPException(
            status_code=400,
            detail="InboxAnchor could not determine the target inbox for this alias.",
        )

    if _managed_aliases_ready():
        alias_domain = _managed_alias_domain()
        alias = _generate_managed_alias(
            alias_domain,
            label=payload.label,
            purpose=payload.purpose,
        )
        alias_type = "managed"
        provider = "inboxanchor"
        note = (
            f"InboxAnchor-managed privacy alias on {alias_domain}. "
            f"It routes into {target_email} through InboxAnchor's managed "
            "inbound worker. "
            "Revoking it in InboxAnchor blocks future reuse here."
        )
    else:
        managed_configured_but_not_ready = _managed_aliases_enabled()
        if managed_configured_but_not_ready and not _plus_alias_fallback_enabled():
            raise HTTPException(
                status_code=503,
                detail=(
                    "InboxAnchor managed aliases are configured but not live yet. "
                    + " ".join(_managed_alias_blockers())
                ),
            )
        if not _plus_alias_fallback_enabled():
            raise HTTPException(
                status_code=400,
                detail=(
                    "InboxAnchor alias domain is not configured yet. Managed aliases like "
                    "travel1234567@inboxanchor.com need INBOXANCHOR_ALIAS_MANAGED_ENABLED=true, "
                    "INBOXANCHOR_ALIAS_DOMAIN=<your-domain>, and inbound forwarding. "
                    "Gmail plus-addressing fallback is disabled so InboxAnchor does not expose "
                    "your real mailbox address."
                ),
            )
        if connection.status != "connected":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Connect Gmail first before generating privacy aliases. "
                    "Without an InboxAnchor alias domain, the fallback mode "
                    "uses Gmail plus-addressing."
                ),
            )
        alias = _generate_plus_alias(
            target_email,
            label=payload.label,
            purpose=payload.purpose,
        )
        alias_type = "plus"
        provider = "gmail"
        if managed_configured_but_not_ready:
            note = (
                "Managed InboxAnchor aliases are not live yet, so InboxAnchor generated a "
                "working Gmail fallback alias instead. "
                + " ".join(_managed_alias_blockers())
                + " This fallback still lands in your mailbox automatically, but it exposes "
                "part of the underlying inbox address because Gmail requires the original "
                "local-part before the + tag."
            )
        else:
            note = (
                "Fallback Gmail alias. It still lands in your mailbox automatically, but it "
                "exposes part of the underlying inbox address because Gmail requires the "
                "original local-part before the + tag."
            )
    routing_label = _configure_alias_inbox_routing(
        alias_address=alias,
        label=payload.label,
        purpose=payload.purpose,
    )
    if routing_label:
        note = (
            f"{note} New mail to this alias is auto-labeled into {routing_label} "
            "and skipped from the main inbox."
        )
    with session_scope() as session:
        repository = InboxRepository(session)
        stored = repository.create_email_alias(
            EmailAlias(
                owner_email=actor_email,
                provider=provider,
                alias_address=alias,
                target_email=target_email,
                alias_type=alias_type,
                label=payload.label.strip(),
                purpose=payload.purpose.strip(),
                note=note,
                created_at=datetime.now(timezone.utc),
            )
        )
    return stored.model_dump(mode="json")


@router.post("/aliases/{alias_id}/revoke")
def frontend_revoke_alias(
    alias_id: int,
    authorization: Optional[str] = Header(default=None),
):
    actor_email = _require_actor_email(authorization)
    with session_scope() as session:
        repository = InboxRepository(session)
        alias = repository.get_email_alias(alias_id)
        if alias is None:
            raise HTTPException(status_code=404, detail="Alias not found.")
        if alias.owner_email != actor_email:
            raise HTTPException(status_code=403, detail="You can only revoke your own aliases.")
        _remove_alias_inbox_routing(alias.alias_address)
        revoked = repository.revoke_email_alias(alias_id)
    if revoked is None:
        raise HTTPException(status_code=404, detail="Alias not found.")
    return revoked.model_dump(mode="json")


@router.post("/aliases/resolve")
def frontend_resolve_alias(
    payload: AliasResolveRequest,
    x_inboxanchor_alias_secret: Optional[str] = Header(default=None),
):
    _require_alias_resolver_secret(x_inboxanchor_alias_secret)
    alias_address = _normalize_alias_address(payload.alias_address)
    with session_scope() as session:
        repository = InboxRepository(session)
        alias = repository.get_email_alias_by_address(alias_address)
    if alias is None:
        return {
            "active": False,
            "action": "reject",
            "reason": "Alias not found.",
            "alias_address": alias_address,
        }
    if alias.status != "active":
        return {
            "active": False,
            "action": "reject",
            "reason": "Alias has been revoked.",
            "alias_address": alias.alias_address,
        }
    resolved = _alias_resolution_payload(alias)
    return {
        "active": True,
        "action": "forward",
        **resolved,
    }


@router.get("/digest")
def frontend_digest(time_range: str = ""):
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    run_id = _get_cached_or_latest_run_id(provider_name, time_range=time_range or None)
    digest = _build_cache_digest(provider_name, time_range=time_range or None, run_id=run_id)
    return {
        "totalUnread": digest["total_unread"],
        "categoryCounts": digest["category_counts"],
        "highPriorityIds": digest["high_priority_ids"],
        "summary": digest["summary"],
    }


@router.get("/ops/overview")
def frontend_ops_overview(provider: str = "", time_range: str = ""):
    provider_name = _get_provider_name(provider or None)
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    run_id = _get_cached_or_latest_run_id(provider_name, time_range=time_range or None)
    return _build_ops_overview(provider_name, run_id, time_range=time_range or None)


@router.get("/ops/progress")
def frontend_ops_progress(provider: str = "", time_range: str = ""):
    provider_name = _get_provider_name(provider or None)
    normalized_time_range = normalize_time_range(time_range or None)
    scope_key = _scope_key(provider_name, normalized_time_range)
    progress = FRONTEND_PROGRESS.get(scope_key)
    active_job = None
    with FRONTEND_ACTIVE_RUNS_LOCK:
        candidate = FRONTEND_ACTIVE_RUNS.get(scope_key)
        if candidate is not None and not candidate.event.is_set():
            active_job = candidate
    if progress:
        if _should_reconcile_stale_scan_progress(progress, scope_key):
            run_id = _get_cached_or_latest_run_id(
                provider_name,
                time_range=normalized_time_range,
            )
            if run_id:
                try:
                    synthesized = _synthesized_complete_progress(
                        provider_name,
                        run_id,
                        time_range=normalized_time_range,
                        previous=progress,
                    )
                except HTTPException:
                    synthesized = None
                if synthesized is not None:
                    FRONTEND_PROGRESS[scope_key] = synthesized
                    FRONTEND_PROVIDER_ERRORS.pop(scope_key, None)
                    return synthesized
        if active_job is not None and progress.get("mode") != active_job.mode:
            progress = dict(progress)
            progress["mode"] = active_job.mode
            progress["status"] = "running"
            progress["stage"] = "queued"
            progress["updated_at"] = datetime.now(timezone.utc).isoformat()
            FRONTEND_PROGRESS[scope_key] = progress
        return progress
    if active_job is not None:
        queued = {
            "provider": provider_name,
            "time_range": normalized_time_range,
            "time_range_label": time_range_label(normalized_time_range),
            "mode": active_job.mode,
            "status": "running",
            "stage": "queued",
            "target_count": 0,
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
            "oldest_cached_at": None,
            "newest_cached_at": None,
            "latest_subject": None,
            "latest_action": None,
            "resume_offset": 0,
            "remaining_count": 0,
            "completed": False,
            "run_id": active_job.run_id,
            "error": active_job.error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        FRONTEND_PROGRESS[scope_key] = queued
        return queued
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    sync_state = _load_mailbox_sync_state(provider_name, time_range=normalized_time_range)
    if sync_state:
        sync_unread_only = _mailbox_workflow_unread_filter(sync_state.get("unread_only"))
        workflow_counts = _load_mailbox_workflow_counts(
            provider_name,
            unread_only=sync_unread_only,
            time_range=normalized_time_range,
        )
        full_mailbox_mode = bool(sync_state.get("full_mailbox"))
        processed_count = max(
            int(sync_state.get("processed_count") or 0),
            cache_stats["cached_count"],
        )
        resume_offset = max(
            int(sync_state.get("next_offset") or 0),
            processed_count,
        )
        completed = bool(sync_state.get("completed"))
        if full_mailbox_mode:
            target_count = processed_count if completed else 0
            remaining_count = 0
        else:
            target_count = int(sync_state.get("target_count") or 0)
            remaining_count = max(target_count - resume_offset, 0)
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
            "action_item_count": workflow_counts["action_item_count"],
            "recommendation_count": workflow_counts["recommendation_count"],
            "batch_count": int(sync_state.get("batch_count") or 0),
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": cache_stats["hydrated_count"],
            "labeled_count": int(sync_state.get("labeled_count") or 0),
            "labels_removed_count": int(sync_state.get("labels_removed_count") or 0),
            "archived_count": int(sync_state.get("archived_count") or 0),
            "marked_read_count": int(sync_state.get("marked_read_count") or 0),
            "trashed_count": int(sync_state.get("trashed_count") or 0),
            "reply_sent_count": int(sync_state.get("reply_sent_count") or 0),
            "oldest_cached_at": cache_stats["oldest_cached_at"],
            "newest_cached_at": cache_stats["newest_cached_at"],
            "latest_subject": sync_state.get("latest_subject"),
            "latest_action": sync_state.get("latest_action"),
            "resume_offset": resume_offset,
            "remaining_count": remaining_count,
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
        "labeled_count": 0,
        "labels_removed_count": 0,
        "archived_count": 0,
        "marked_read_count": 0,
        "trashed_count": 0,
        "reply_sent_count": 0,
        "oldest_cached_at": None,
        "newest_cached_at": None,
        "latest_subject": None,
        "latest_action": None,
        "resume_offset": 0,
        "remaining_count": 0,
        "completed": False,
        "run_id": FRONTEND_RUN_CACHE.get(scope_key),
        "error": FRONTEND_PROVIDER_ERRORS.get(scope_key),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/ops/scan")
def frontend_ops_scan(payload: FrontendProviderWorkflowRequest):
    provider_name = _get_provider_name(payload.provider)
    _start_unread_sync_job(
        provider_name,
        force_refresh=payload.force_refresh,
        time_range=payload.time_range,
    )
    run_id = _get_cached_or_latest_run_id(provider_name, time_range=payload.time_range)
    return _build_ops_overview(provider_name, run_id, time_range=payload.time_range)


@router.post("/ops/classify-cache")
def frontend_ops_classify_cache(payload: FrontendProviderWorkflowRequest):
    provider_name = _get_provider_name(payload.provider)
    _maybe_seed_mailbox_cache(provider_name, time_range=payload.time_range)
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=payload.time_range)
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "running",
            "stage": "classifying_cache",
            "limit": cache_stats["cached_unread_count"],
            "processed_emails": 0,
            "read_count": cache_stats["cached_unread_count"],
            "action_item_count": 0,
            "recommendation_count": 0,
            "labeled_count": 0,
            "archived_count": 0,
            "marked_read_count": 0,
            "trashed_count": 0,
            "reply_sent_count": 0,
            "latest_action": "classify",
            "error": None,
        },
        time_range=payload.time_range,
    )
    result = _enrich_mailbox_cache(
        provider_name,
        unread_only=True,
        time_range=payload.time_range,
        force_refresh=payload.force_refresh,
    )
    refreshed_run_id = _get_cached_or_latest_run_id(
        provider_name,
        time_range=payload.time_range,
    )
    overview = _build_ops_overview(
        provider_name,
        refreshed_run_id,
        time_range=payload.time_range,
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "complete",
            "stage": "classification_ready",
            "limit": cache_stats["cached_unread_count"],
            "processed_emails": result["count"],
            "read_count": cache_stats["cached_unread_count"],
            "action_item_count": result["action_item_count"],
            "recommendation_count": result["recommendation_count"],
            "latest_subject": result["latest_subject"],
            "latest_action": "classify",
            "error": None,
        },
        time_range=payload.time_range,
    )
    STREAM_HUB.emit(
        {
            "type": "mailbox_classification_completed",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "count": result["count"],
        }
    )
    return {"count": result["count"], "overview": overview}


def _start_mailbox_backfill_job(
    provider_name: str,
    payload: FrontendMailboxBackfillRequest,
) -> bool:
    normalized_time_range = normalize_time_range(payload.time_range)
    scope_key = _scope_key(provider_name, normalized_time_range)
    job, wait_job = _claim_frontend_job(
        scope_key,
        provider_name=provider_name,
        mode="backfill",
    )
    if wait_job is not None:
        return False
    assert job is not None

    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=normalized_time_range)
    workflow_counts = _load_mailbox_workflow_counts(
        provider_name,
        unread_only=_mailbox_workflow_unread_filter(payload.unread_only),
        time_range=normalized_time_range,
    )
    sync_state = _load_mailbox_sync_state(provider_name, time_range=normalized_time_range) or {}
    resume_offset = max(
        int(sync_state.get("next_offset") or 0),
        int(sync_state.get("processed_count") or 0),
        cache_stats["cached_count"],
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "backfill",
            "status": "running",
            "stage": "queued",
            "limit": payload.limit,
            "processed_emails": resume_offset,
            "read_count": resume_offset,
            "action_item_count": workflow_counts["action_item_count"],
            "recommendation_count": workflow_counts["recommendation_count"],
            "batch_count": int(sync_state.get("batch_count") or 0),
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": max(
                int(sync_state.get("hydrated_count") or 0),
                cache_stats["hydrated_count"],
            ),
            "oldest_cached_at": cache_stats["oldest_cached_at"],
            "newest_cached_at": cache_stats["newest_cached_at"],
            "latest_subject": sync_state.get("latest_subject"),
            "resume_offset": resume_offset,
            "remaining_count": _mailbox_limit_remaining(payload.limit, resume_offset),
            "completed": False,
            "run_id": _get_cached_or_latest_run_id(
                provider_name,
                time_range=normalized_time_range,
            ),
            "error": None,
        },
        time_range=normalized_time_range,
    )

    def _runner() -> None:
        try:
            frontend_ops_backfill(payload.model_copy(update={"background": False}))
        except HTTPException:
            return
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
        finally:
            with FRONTEND_ACTIVE_RUNS_LOCK:
                finished_job = FRONTEND_ACTIVE_RUNS.pop(scope_key, None)
            if finished_job is not None:
                finished_job.event.set()

    threading.Thread(
        target=_runner,
        name=f"inboxanchor-backfill-{provider_name}-{normalized_time_range}",
        daemon=True,
    ).start()
    return True


@router.post("/ops/backfill")
def frontend_ops_backfill(payload: FrontendMailboxBackfillRequest):
    provider_name = _get_provider_name(payload.provider)
    full_mailbox_mode = payload.limit is None
    if payload.background and (
        full_mailbox_mode or payload.limit > MAILBOX_BACKFILL_BACKGROUND_THRESHOLD
    ):
        normalized_time_range = normalize_time_range(payload.time_range)
        _start_mailbox_backfill_job(provider_name, payload)
        cache_stats = _load_mailbox_cache_stats(
            provider_name,
            time_range=normalized_time_range,
        )
        sync_state = _load_mailbox_sync_state(
            provider_name,
            time_range=normalized_time_range,
        ) or {}
        processed_total = max(
            int(sync_state.get("processed_count") or 0),
            cache_stats["cached_count"],
        )
        resume_offset = max(
            int(sync_state.get("next_offset") or 0),
            processed_total,
        )
        return {
            "count": 0,
            "processedTotal": processed_total,
            "cachedCount": cache_stats["cached_count"],
            "hydratedCount": cache_stats["hydrated_count"],
            "resumeOffset": resume_offset,
            "remainingCount": _mailbox_limit_remaining(payload.limit, resume_offset),
            "completed": False,
            "overview": _build_ops_overview(
                provider_name,
                _get_cached_or_latest_run_id(
                    provider_name,
                    time_range=normalized_time_range,
                ),
                time_range=normalized_time_range,
            ),
        }
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
    workflow_counts = _load_mailbox_workflow_counts(
        provider_name,
        unread_only=_mailbox_workflow_unread_filter(payload.unread_only),
        time_range=normalized_time_range,
    )

    if (
        sync_state
        and not payload.force_refresh
        and bool(sync_state.get("include_body")) == payload.include_body
        and bool(sync_state.get("unread_only")) == payload.unread_only
        and normalize_time_range(sync_state.get("time_range")) == normalized_time_range
        and bool(sync_state.get("full_mailbox")) == full_mailbox_mode
    ):
        start_offset = max(
            int(sync_state.get("next_offset") or 0),
            int(sync_state.get("processed_count") or 0),
            cache_stats["cached_count"],
        )
        if payload.limit is not None:
            start_offset = min(start_offset, payload.limit)
        processed_total = max(
            int(sync_state.get("processed_count") or 0),
            cache_stats["cached_count"],
            start_offset,
        )
        hydrated_total = max(
            int(sync_state.get("hydrated_count") or 0),
            cache_stats["hydrated_count"],
        )
        batch_count = int(sync_state.get("batch_count") or 0)
        latest_subject = sync_state.get("latest_subject")
        if bool(sync_state.get("completed")) and (
            full_mailbox_mode or _mailbox_limit_reached(payload.limit, start_offset)
        ):
            run_id = _get_cached_or_latest_run_id(
                provider_name,
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
                    "limit": _mailbox_progress_target(
                        payload.limit,
                        processed_total,
                        full_mailbox_mode=full_mailbox_mode,
                        completed=True,
                    ),
                    "processed_emails": processed_total,
                    "read_count": processed_total,
                    "action_item_count": workflow_counts["action_item_count"],
                    "recommendation_count": workflow_counts["recommendation_count"],
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
            "limit": payload.limit or 0,
            "processed_emails": processed_total,
            "read_count": processed_total,
            "action_item_count": workflow_counts["action_item_count"],
            "recommendation_count": workflow_counts["recommendation_count"],
            "batch_count": batch_count,
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": cache_stats["hydrated_count"],
            "oldest_cached_at": cache_stats["oldest_cached_at"],
            "newest_cached_at": cache_stats["newest_cached_at"],
            "latest_subject": latest_subject,
            "resume_offset": start_offset,
            "remaining_count": _mailbox_limit_remaining(payload.limit, start_offset),
            "completed": False,
            "error": None,
        },
        time_range=normalized_time_range,
    )

    try:
        for batch in service.provider.iter_mailbox_batches(
            limit=None if payload.limit is None else max(payload.limit - start_offset, 0),
            batch_size=payload.batch_size,
            include_body=payload.include_body,
            unread_only=payload.unread_only,
            offset=start_offset,
            time_range=normalized_time_range,
        ):
            batch_count += 1
            with session_scope() as session:
                repository = InboxRepository(session)
                batch_ids = _sync_mailbox_batch(repository, provider_name, batch)
                processed_this_run += len(batch_ids)
                processed_total += len(batch_ids)
                for email in batch:
                    if (email.body_full or "").strip():
                        hydrated_total += 1
                cache_stats = repository.get_mailbox_cache_stats(
                    provider_name,
                    time_range=normalized_time_range,
                )
                workflow_counts = _load_mailbox_workflow_counts(
                    provider_name,
                    unread_only=_mailbox_workflow_unread_filter(payload.unread_only),
                    time_range=normalized_time_range,
                )
                repository.save_provider_sync_state(
                    provider_name,
                    sync_kind,
                    {
                        "target_count": payload.limit,
                        "full_mailbox": full_mailbox_mode,
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
                        "action_item_count": workflow_counts["action_item_count"],
                        "recommendation_count": workflow_counts["recommendation_count"],
                    },
                )
            latest_subject = batch[0].subject if batch else latest_subject
            _update_frontend_progress(
                provider_name,
                {
                    "mode": "backfill",
                    "status": "running",
                    "stage": "backfill_resume" if start_offset else "backfill_index",
                    "limit": payload.limit or 0,
                    "processed_emails": processed_total,
                    "read_count": processed_total,
                    "action_item_count": workflow_counts["action_item_count"],
                    "recommendation_count": workflow_counts["recommendation_count"],
                    "batch_count": batch_count,
                    "cached_count": cache_stats["cached_count"],
                    "hydrated_count": max(hydrated_total, cache_stats["hydrated_count"]),
                    "oldest_cached_at": cache_stats["oldest_cached_at"],
                    "newest_cached_at": cache_stats["newest_cached_at"],
                    "latest_subject": latest_subject,
                    "resume_offset": processed_total,
                    "remaining_count": _mailbox_limit_remaining(payload.limit, processed_total),
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
    completed = True if full_mailbox_mode else (
        _mailbox_limit_reached(payload.limit, processed_total) or processed_this_run == 0
    )
    with session_scope() as session:
        repository = InboxRepository(session)
        recommendation_stats = repository.get_mailbox_recommendation_stats(
            provider_name,
            unread_only=_mailbox_workflow_unread_filter(payload.unread_only),
            time_range=normalized_time_range,
        )
        workflow_counts = {
            "action_item_count": repository.count_mailbox_action_items(
                provider_name,
                unread_only=_mailbox_workflow_unread_filter(payload.unread_only),
                time_range=normalized_time_range,
            ),
            "recommendation_count": (
                int(recommendation_stats["safe_count"])
                + int(recommendation_stats["review_count"])
                + int(recommendation_stats["blocked_count"])
            ),
        }
        repository.save_provider_sync_state(
            provider_name,
            sync_kind,
            {
                "target_count": payload.limit,
                "full_mailbox": full_mailbox_mode,
                "processed_count": processed_total,
                "next_offset": (
                    processed_total
                    if payload.limit is None
                    else min(processed_total, payload.limit)
                ),
                "batch_count": batch_count,
                "hydrated_count": max(hydrated_total, cache_stats["hydrated_count"]),
                "cached_count": cache_stats["cached_count"],
                "include_body": payload.include_body,
                "unread_only": payload.unread_only,
                "time_range": normalized_time_range,
                "completed": completed,
                "latest_subject": latest_subject,
                "action_item_count": workflow_counts["action_item_count"],
                "recommendation_count": workflow_counts["recommendation_count"],
            },
        )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "backfill",
            "status": "complete",
            "stage": "backfill_ready",
            "limit": _mailbox_progress_target(
                payload.limit,
                processed_total,
                full_mailbox_mode=full_mailbox_mode,
                completed=completed,
            ),
            "processed_emails": processed_total,
            "read_count": processed_total,
            "action_item_count": workflow_counts["action_item_count"],
            "recommendation_count": workflow_counts["recommendation_count"],
            "batch_count": batch_count,
            "cached_count": cache_stats["cached_count"],
            "hydrated_count": cache_stats["hydrated_count"],
            "oldest_cached_at": cache_stats["oldest_cached_at"],
            "newest_cached_at": cache_stats["newest_cached_at"],
            "latest_subject": latest_subject,
            "resume_offset": (
                processed_total
                if payload.limit is None
                else min(processed_total, payload.limit)
            ),
            "remaining_count": _mailbox_limit_remaining(payload.limit, processed_total),
            "completed": completed,
            "error": None,
        },
        time_range=normalized_time_range,
    )

    run_id = _get_cached_or_latest_run_id(provider_name, time_range=normalized_time_range)
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
        "resumeOffset": (
            processed_total
            if payload.limit is None
            else min(processed_total, payload.limit)
        ),
        "remainingCount": _mailbox_limit_remaining(payload.limit, processed_total),
        "completed": completed,
        "overview": overview,
    }


@router.post("/ops/auto-label")
def frontend_ops_auto_label(payload: FrontendProviderWorkflowRequest):
    provider_name = payload.provider or _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=payload.time_range)
    if payload.force_refresh:
        _enrich_mailbox_cache(
            provider_name,
            unread_only=True,
            time_range=payload.time_range,
            force_refresh=True,
        )
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=payload.time_range)
    applied_count = 0
    scanned_count = 0
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "running",
            "stage": "applying_labels",
            "limit": cache_stats["cached_unread_count"],
            "processed_emails": 0,
            "read_count": cache_stats["cached_unread_count"],
            "labeled_count": 0,
            "archived_count": 0,
            "marked_read_count": 0,
            "trashed_count": 0,
            "reply_sent_count": 0,
            "latest_action": "label",
            "error": None,
        },
        time_range=payload.time_range,
    )
    for detail in _iter_mailbox_recommendation_details(
        provider_name,
        time_range=payload.time_range,
        unread_only=True,
    ):
        scanned_count += 1
        labels = _recommended_labels_for_email(detail)
        if not labels:
            continue
        classification = detail["classification"]
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
        applied_count += 1
        _update_frontend_progress(
            provider_name,
            {
                "mode": "workflow",
                "status": "running",
                "stage": "applying_labels",
                "limit": cache_stats["cached_unread_count"],
                "processed_emails": scanned_count,
                "read_count": cache_stats["cached_unread_count"],
                "labeled_count": applied_count,
                "latest_subject": detail["subject"],
                "latest_action": "label",
            },
            time_range=payload.time_range,
        )

    refreshed_run_id = _get_cached_or_latest_run_id(
        provider_name,
        time_range=payload.time_range,
    )
    overview = _build_ops_overview(
        provider_name,
        refreshed_run_id,
        time_range=payload.time_range,
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "complete",
            "stage": "labels_ready",
            "limit": cache_stats["cached_unread_count"],
            "processed_emails": scanned_count,
            "read_count": cache_stats["cached_unread_count"],
            "labeled_count": applied_count,
            "latest_action": "label",
            "error": None,
        },
        time_range=payload.time_range,
    )
    STREAM_HUB.emit(
        {
            "type": "auto_label_completed",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "count": applied_count,
        }
    )
    return {"applied": [], "count": applied_count, "overview": overview}


@router.post("/ops/clean-labels")
def frontend_ops_clean_labels(payload: FrontendProviderWorkflowRequest):
    provider_name = payload.provider or _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=payload.time_range)
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=payload.time_range)
    scanned_count = 0
    removed_count = 0
    removed_label_names: list[str] = []
    provider_cleanup_labels = (
        _list_provider_cleanup_labels(provider_name) if provider_name == "gmail" else []
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "running",
            "stage": "cleaning_labels",
            "limit": cache_stats["cached_unread_count"],
            "processed_emails": 0,
            "read_count": cache_stats["cached_unread_count"],
            "labeled_count": 0,
            "labels_removed_count": 0,
            "archived_count": 0,
            "marked_read_count": 0,
            "trashed_count": 0,
            "reply_sent_count": 0,
            "latest_action": "remove_labels",
            "error": None,
        },
        time_range=payload.time_range,
    )
    use_global_label_delete = provider_name == "gmail"
    if use_global_label_delete:
        for detail in _iter_mailbox_recommendation_details(
            provider_name,
            time_range=payload.time_range,
            unread_only=True,
        ):
            scanned_count += 1
            removed_label_names.extend(_labels_to_remove_for_email(detail))
            _update_frontend_progress(
                provider_name,
                {
                    "mode": "workflow",
                    "status": "running",
                    "stage": "collecting_labels",
                    "limit": cache_stats["cached_unread_count"],
                    "processed_emails": scanned_count,
                    "read_count": cache_stats["cached_unread_count"],
                    "labels_removed_count": 0,
                    "latest_subject": detail["subject"],
                    "latest_action": "remove_labels",
                },
                time_range=payload.time_range,
            )
        cleanup_label_names = dedupe_labels(removed_label_names + provider_cleanup_labels)
        deleted_label_names: list[str] = []
        for index, label_name in enumerate(cleanup_label_names, start=1):
            deleted = _delete_provider_labels(provider_name, [label_name])
            deleted_label_names.extend(deleted["deletedLabels"])
            _update_frontend_progress(
                provider_name,
                {
                    "mode": "workflow",
                    "status": "running",
                    "stage": "deleting_label_definitions",
                    "limit": len(cleanup_label_names),
                    "processed_emails": index,
                    "read_count": cache_stats["cached_unread_count"],
                    "labels_removed_count": 0,
                    "latest_subject": label_name,
                    "latest_action": "remove_labels",
                },
                time_range=payload.time_range,
            )
        deleted_label_names = dedupe_labels(deleted_label_names)
        deleted_labels = {
            "provider": provider_name,
            "action": "delete_labels",
            "deletedLabels": deleted_label_names,
            "deletedCount": len(deleted_label_names),
            "details": (
                "Deleted InboxAnchor Gmail label definitions directly."
                if deleted_label_names
                else "No InboxAnchor Gmail label definitions needed pruning."
            ),
        }
        removed_count = scanned_count
        _update_frontend_progress(
            provider_name,
            {
                "mode": "workflow",
                "status": "running",
                "stage": "syncing_local_cache",
                "limit": len(cleanup_label_names),
                "processed_emails": deleted_labels["deletedCount"],
                "read_count": cache_stats["cached_unread_count"],
                "labels_removed_count": removed_count,
                "latest_subject": (
                    f"Deleted {deleted_labels['deletedCount']} Gmail label definitions"
                ),
                "latest_action": "remove_labels",
            },
            time_range=payload.time_range,
        )
        with session_scope() as session:
            repository = InboxRepository(session)
            run_id = repository.get_latest_run_id(provider_name)
            if run_id:
                repository.remove_labels_from_run_emails(
                    run_id,
                    deleted_labels["deletedLabels"],
                )
            repository.remove_labels_from_mailbox(
                provider_name,
                deleted_labels["deletedLabels"],
            )
    else:
        removed_email_ids: list[str] = []
        for detail in _iter_mailbox_recommendation_details(
            provider_name,
            time_range=payload.time_range,
            unread_only=True,
        ):
            scanned_count += 1
            labels = _labels_to_remove_for_email(detail)
            if not labels:
                continue
            classification = detail["classification"]
            _remove_provider_labels(
                provider_name,
                detail["email_id"],
                labels,
                reason=(
                    "Removed InboxAnchor-generated labels without changing the "
                    "email itself."
                ),
                confidence=classification["confidence"],
                approved_by_user=True,
                safety_status=SafetyStatus.allowed,
            )
            removed_email_ids.append(detail["email_id"])
            removed_label_names.extend(labels)
            removed_count += 1
            _update_frontend_progress(
                provider_name,
                {
                    "mode": "workflow",
                    "status": "running",
                    "stage": "cleaning_labels",
                    "limit": cache_stats["cached_unread_count"],
                    "processed_emails": scanned_count,
                    "read_count": cache_stats["cached_unread_count"],
                    "labels_removed_count": removed_count,
                    "latest_subject": detail["subject"],
                    "latest_action": "remove_labels",
                },
                time_range=payload.time_range,
            )
        removed_label_names = dedupe_labels(removed_label_names)
        deleted_labels = _delete_provider_labels(provider_name, removed_label_names)
        with session_scope() as session:
            repository = InboxRepository(session)
            run_id = repository.get_latest_run_id(provider_name)
            if run_id:
                repository.remove_labels_from_run_emails(
                    run_id,
                    removed_label_names,
                    email_ids=removed_email_ids,
                )
            repository.remove_labels_from_mailbox(
                provider_name,
                removed_label_names,
                email_ids=removed_email_ids,
            )

    refreshed_run_id = _get_cached_or_latest_run_id(
        provider_name,
        time_range=payload.time_range,
    )
    overview = _build_ops_overview(
        provider_name,
        refreshed_run_id,
        time_range=payload.time_range,
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "complete",
            "stage": "labels_reset",
            "limit": cache_stats["cached_unread_count"],
            "processed_emails": scanned_count,
            "read_count": cache_stats["cached_unread_count"],
            "labels_removed_count": removed_count,
            "latest_subject": (
                f"Deleted {deleted_labels['deletedCount']} label definitions"
                if deleted_labels["deletedCount"]
                else None
            ),
            "latest_action": "remove_labels",
            "error": None,
        },
        time_range=payload.time_range,
    )
    STREAM_HUB.emit(
        {
            "type": "label_cleanup_completed",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "count": removed_count,
            "deleted_labels": deleted_labels["deletedCount"],
        }
    )
    return {
        "applied": [],
        "count": removed_count,
        "deletedLabelCount": deleted_labels["deletedCount"],
        "deletedLabels": deleted_labels["deletedLabels"],
        "overview": overview,
    }


@router.post("/ops/safe-cleanup")
def frontend_ops_safe_cleanup(payload: FrontendProviderWorkflowRequest):
    provider_name = payload.provider or _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=payload.time_range)
    if payload.force_refresh:
        _enrich_mailbox_cache(
            provider_name,
            unread_only=True,
            time_range=payload.time_range,
            force_refresh=True,
        )
    existing_progress = FRONTEND_PROGRESS.get(
        _scope_key(provider_name, payload.time_range),
        {},
    )
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=payload.time_range)
    with session_scope() as session:
        repository = InboxRepository(session)
        recommendation_stats = repository.get_mailbox_recommendation_stats(
            provider_name,
            unread_only=True,
            time_range=normalize_time_range(payload.time_range),
        )
    safe_target_count = int(recommendation_stats["safe_count"])
    applied_count = 0
    labeled_count = int(existing_progress.get("labeled_count", 0))
    archived_count = 0
    marked_read_count = 0
    trashed_count = 0
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "running",
            "stage": "safe_cleanup",
            "limit": safe_target_count,
            "processed_emails": 0,
            "read_count": cache_stats["cached_unread_count"],
            "labeled_count": labeled_count,
            "archived_count": 0,
            "marked_read_count": 0,
            "trashed_count": 0,
            "reply_sent_count": 0,
            "latest_action": "cleanup",
            "error": None,
        },
        time_range=payload.time_range,
    )
    for detail in _iter_mailbox_recommendation_details(
        provider_name,
        time_range=payload.time_range,
        unread_only=True,
    ):
        recommendation = _frontend_recommendation_payload(
            detail,
            blocked=detail["email_id"] in blocked,
        )
        if recommendation["status"] != "safe":
            continue
        _apply_provider_action(
            provider_name,
            recommendation["emailId"],
            recommendation["recommendedAction"],
            recommendation["proposedLabels"],
            reason=recommendation["reason"],
            confidence=recommendation["confidence"],
            approved_by_user=True,
            safety_status=SafetyStatus.allowed,
        )
        applied_count += 1
        if recommendation["proposedLabels"]:
            labeled_count += 1
        if recommendation["recommendedAction"] == "archive":
            archived_count += 1
        elif recommendation["recommendedAction"] == "mark_read":
            marked_read_count += 1
        elif recommendation["recommendedAction"] == "trash":
            trashed_count += 1
        _update_frontend_progress(
            provider_name,
            {
                "mode": "workflow",
                "status": "running",
                "stage": "safe_cleanup",
                "limit": safe_target_count,
                "processed_emails": applied_count,
                "read_count": cache_stats["cached_unread_count"],
                "labeled_count": labeled_count,
                "archived_count": archived_count,
                "marked_read_count": marked_read_count,
                "trashed_count": trashed_count,
                "latest_subject": detail.get("subject")
                or detail.get("email", {}).get("subject"),
                "latest_action": recommendation["recommendedAction"],
            },
            time_range=payload.time_range,
        )

    refreshed_run_id = _get_cached_or_latest_run_id(
        provider_name,
        time_range=payload.time_range,
    )
    overview = _build_ops_overview(
        provider_name,
        refreshed_run_id,
        time_range=payload.time_range,
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "complete",
            "stage": "cleanup_ready",
            "limit": safe_target_count,
            "processed_emails": applied_count,
            "read_count": cache_stats["cached_unread_count"],
            "labeled_count": labeled_count,
            "archived_count": archived_count,
            "marked_read_count": marked_read_count,
            "trashed_count": trashed_count,
            "latest_action": "cleanup",
            "error": None,
        },
        time_range=payload.time_range,
    )
    STREAM_HUB.emit(
        {
            "type": "safe_cleanup_completed",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "count": applied_count,
        }
    )
    return {"applied": [], "count": applied_count, "overview": overview}


@router.post("/ops/industrial-read")
def frontend_ops_industrial_read(payload: FrontendProviderWorkflowRequest):
    provider_name = payload.provider or _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=payload.time_range)
    cache_stats = _load_mailbox_cache_stats(provider_name, time_range=payload.time_range)
    unread_target_count = cache_stats["cached_unread_count"]
    processed_count = 0
    marked_read_count = 0
    batch_count = 0
    batch_size = 500
    latest_subject: Optional[str] = None

    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "running",
            "stage": "industrial_read",
            "limit": unread_target_count,
            "processed_emails": 0,
            "read_count": unread_target_count,
            "action_item_count": 0,
            "recommendation_count": 0,
            "batch_count": 0,
            "marked_read_count": 0,
            "latest_action": "mark_read",
            "error": None,
        },
        time_range=payload.time_range,
    )

    while True:
        with session_scope() as session:
            repository = InboxRepository(session)
            batch = repository.list_mailbox_emails(
                provider_name,
                limit=batch_size,
                offset=0,
                unread_only=True,
                time_range=normalize_time_range(payload.time_range),
            )
        if not batch:
            break

        email_ids = [str(item["email_id"]) for item in batch]
        try:
            _service_for_provider(provider_name).provider.batch_mark_as_read(
                email_ids,
                dry_run=False,
            )
        except Exception as exc:
            _raise_provider_runtime_error(provider_name, exc)

        with session_scope() as session:
            repository = InboxRepository(session)
            repository.mark_mailbox_emails_read(provider_name, email_ids)
            run_id = repository.get_latest_run_id(provider_name)
            if run_id:
                repository.mark_run_emails_read(run_id, email_ids)

        processed_count += len(email_ids)
        marked_read_count += len(email_ids)
        batch_count += 1
        latest_subject = batch[0].get("subject") or latest_subject
        _update_frontend_progress(
            provider_name,
            {
                "mode": "workflow",
                "status": "running",
                "stage": "industrial_read",
                "limit": unread_target_count,
                "processed_emails": processed_count,
                "read_count": unread_target_count,
                "batch_count": batch_count,
                "marked_read_count": marked_read_count,
                "latest_subject": latest_subject,
                "latest_action": "mark_read",
                "error": None,
            },
            time_range=payload.time_range,
        )

    refreshed_run_id = _get_cached_or_latest_run_id(
        provider_name,
        time_range=payload.time_range,
    )
    overview = _build_ops_overview(
        provider_name,
        refreshed_run_id,
        time_range=payload.time_range,
    )
    _update_frontend_progress(
        provider_name,
        {
            "mode": "workflow",
            "status": "complete",
            "stage": "industrial_read_complete",
            "limit": unread_target_count,
            "processed_emails": processed_count,
            "read_count": unread_target_count,
            "batch_count": batch_count,
            "marked_read_count": marked_read_count,
            "latest_action": "mark_read",
            "error": None,
        },
        time_range=payload.time_range,
    )
    STREAM_HUB.emit(
        {
            "type": "industrial_read_completed",
            "provider": provider_name,
            "run_id": refreshed_run_id,
            "count": marked_read_count,
        }
    )
    return {"applied": [], "count": marked_read_count, "overview": overview}


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
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    blocked = FRONTEND_BLOCK_REGISTRY.setdefault(provider_name, set())
    details = _load_mailbox_recommendation_details(
        provider_name,
        time_range=time_range or None,
        unread_only=True,
    )
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

    refreshed_run_id = _get_cached_or_latest_run_id(
        provider_name,
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
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    detail = _find_mailbox_recommendation_detail(
        provider_name,
        email_id,
        time_range=time_range or None,
    )
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
    refreshed_run_id = _get_cached_or_latest_run_id(
        provider_name,
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
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    detail = _find_mailbox_recommendation_detail(
        provider_name,
        email_id,
        time_range=time_range or None,
    )
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
    return {"ok": True, **result}


@router.post("/recommendations/{email_id}/block")
def frontend_block_recommendation(
    email_id: str,
    payload: FrontendRecommendationActionRequest,
    authorization: Optional[str] = Header(default=None),
    time_range: str = "",
):
    provider_name = _get_provider_name()
    _maybe_seed_mailbox_cache(provider_name, time_range=time_range or None)
    detail = _find_mailbox_recommendation_detail(
        provider_name,
        email_id,
        time_range=time_range or None,
    )
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
            "run_id": _get_cached_or_latest_run_id(provider_name, time_range=time_range or None),
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
