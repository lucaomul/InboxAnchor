from __future__ import annotations

from inboxanchor.models import EmailActionItem, EmailMessage


class ActionExtractorAgent:
    def extract(self, email: EmailMessage) -> list[EmailActionItem]:
        text = f"{email.subject}\n{email.snippet}\n{email.body_preview}".lower()
        items: list[EmailActionItem] = []

        if any(token in text for token in ["reply", "respond", "let me know"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="reply_needed",
                    description="A response is likely needed.",
                    requires_reply=True,
                )
            )
        if any(token in text for token in ["schedule", "calendar", "meeting", "availability"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="meeting_scheduling",
                    description="Meeting coordination or scheduling detected.",
                )
            )
        if any(token in text for token in ["invoice", "payment", "due", "receipt"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="invoice_payment",
                    description="Financial follow-up may be required.",
                )
            )
        if any(token in text for token in ["review attached", "document review", "please review"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="document_review",
                    description="A document review step appears to be required.",
                )
            )
        if any(token in text for token in ["deadline", "by eod", "tomorrow", "friday"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="deadline",
                    description="A deadline or time-sensitive commitment was detected.",
                )
            )
        if any(token in text for token in ["follow up", "checking in", "circling back"]):
            items.append(
                EmailActionItem(
                    email_id=email.id,
                    action_type="follow_up",
                    description="A follow-up action may be required.",
                )
            )
        return items
