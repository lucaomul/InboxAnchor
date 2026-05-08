from __future__ import annotations

from fastapi import APIRouter

from inboxanchor.bootstrap import InboxAnchorService
from inboxanchor.connectors.gmail_webhook import GmailPushSubscription

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/gmail")
def gmail_webhook(payload: dict):
    notification = GmailPushSubscription.parse_notification(payload)

    try:
        service = InboxAnchorService(provider_name="gmail")
        settings = service.load_workspace_settings()
        result = service.engine.run(
            dry_run=True,
            limit=settings.default_scan_limit,
            batch_size=settings.default_batch_size,
            confidence_threshold=settings.default_confidence_threshold,
            email_preview_limit=settings.default_email_preview_limit,
            recommendation_preview_limit=settings.default_recommendation_preview_limit,
            workspace_policy=settings.policy,
        )
        return {
            "accepted": True,
            "notification": notification,
            "triage_triggered": True,
            "run_id": result.run_id,
        }
    except Exception as error:
        return {
            "accepted": True,
            "notification": notification,
            "triage_triggered": False,
            "detail": str(error),
        }
