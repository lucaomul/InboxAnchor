from __future__ import annotations

import base64
import json
import logging
import threading

from fastapi import APIRouter, Request

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


@router.post("/gmail")
async def gmail_push_notification(request: Request):
    """
    Ack Gmail Pub/Sub notifications immediately and run incremental triage in the background.
    """

    try:
        body = await request.json()
    except Exception:
        return {"ok": True, "accepted": True, "reason": "malformed_body"}

    message = body.get("message", {})
    data_b64 = message.get("data", "")
    try:
        padded = data_b64 + "=" * (-len(data_b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
    except Exception:
        return {"ok": True, "accepted": True, "reason": "decode_failed"}

    email_address = data.get("emailAddress", "")
    history_id = str(data.get("historyId", ""))
    notification = {
        "email_address": email_address,
        "history_id": history_id,
        "message_id": message.get("messageId", ""),
        "publish_time": message.get("publishTime", ""),
    }

    if not email_address or not history_id:
        return {
            "ok": True,
            "accepted": True,
            "reason": "missing_fields",
            "notification": notification,
        }

    def _run_incremental() -> None:
        from inboxanchor.infra.database import session_scope
        from inboxanchor.infra.repository import InboxRepository
        from inboxanchor.infra.request_context import (
            reset_current_actor_email,
            set_current_actor_email,
        )

        owner_email = None
        with session_scope() as session:
            owner_email = InboxRepository(session).find_provider_connection_owner(
                "gmail",
                email_address,
            )
        if not owner_email:
            logger.info(
                "Ignoring Gmail push notification for unmapped mailbox",
                extra={"email_address": email_address, "history_id": history_id},
            )
            return
        context_token = set_current_actor_email(owner_email)
        try:
            from inboxanchor.api.v1.routers.frontend import (
                STREAM_HUB,
                _get_workspace_settings,
                _service_for_provider,
                _update_frontend_progress,
                mark_frontend_provider_dirty,
            )

            provider_name = "gmail"
            settings = _get_workspace_settings()
            _update_frontend_progress(
                provider_name,
                {
                    "mode": "scan",
                    "status": "running",
                    "stage": "push_refresh",
                    "limit": settings.default_scan_limit,
                    "latest_action": "push_notification",
                    "error": None,
                },
            )
            service = _service_for_provider(provider_name, actor_email=owner_email)
            result = service.engine.run(
                dry_run=True,
                incremental=True,
                limit=settings.default_scan_limit,
                batch_size=settings.default_batch_size,
                confidence_threshold=settings.default_confidence_threshold,
                email_preview_limit=settings.default_email_preview_limit,
                recommendation_preview_limit=settings.default_recommendation_preview_limit,
                workspace_policy=settings.policy,
            )
            mark_frontend_provider_dirty(provider_name)
            STREAM_HUB.emit(
                {
                    "type": "triage_refreshed",
                    "provider": provider_name,
                    "trigger": "push_notification",
                    "new_emails": getattr(result, "total_emails", 0),
                    "history_id": history_id,
                    "run_id": getattr(result, "run_id", None),
                }
            )
        except Exception as exc:  # pragma: no cover - background logging path
            logger.warning(
                "Gmail push triage failed",
                extra={
                    "error": str(exc),
                    "history_id": history_id,
                    "owner_email": owner_email,
                },
            )
        finally:
            reset_current_actor_email(context_token)

    threading.Thread(
        target=_run_incremental,
        daemon=True,
        name="gmail-push-triage",
    ).start()

    return {
        "ok": True,
        "accepted": True,
        "historyId": history_id,
        "emailAddress": email_address,
        "notification": notification,
    }
