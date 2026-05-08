from __future__ import annotations

from typing import Optional

from inboxanchor.models import EmailActionItem, EmailMessage


class ReplyDrafterAgent:
    def draft(
        self,
        email: EmailMessage,
        action_items: list[EmailActionItem],
    ) -> Optional[str]:
        if not action_items:
            return None
        return (
            f"Hi,\n\nThanks for the message about \"{email.subject}\". "
            "I reviewed the thread and noted the next steps. "
            "I will follow up with a fuller response shortly.\n\nBest,\nLuca"
        )
