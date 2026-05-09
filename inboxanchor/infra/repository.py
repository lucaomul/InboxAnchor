from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, func, or_

from inboxanchor.core.time_windows import resolve_time_window
from inboxanchor.infra.database import (
    ActionItemORM,
    AuditLogORM,
    ClassificationORM,
    DomainProfileORM,
    EmailAliasORM,
    EmailRecordORM,
    FollowUpReminderORM,
    MailboxActionItemORM,
    MailboxClassificationORM,
    MailboxEmailORM,
    MailboxRecommendationORM,
    ProviderCheckpointORM,
    ProviderConnectionORM,
    ProviderSyncStateORM,
    RecommendationORM,
    SenderProfileORM,
    TriageRunORM,
    WorkspaceSettingsORM,
)
from inboxanchor.infra.text_normalizer import normalize_email_body_text
from inboxanchor.models import (
    AuditLogEntry,
    EmailActionItem,
    EmailAlias,
    EmailAliasStatus,
    EmailClassification,
    EmailRecommendation,
    FollowUpReminder,
    FollowUpReminderStatus,
    ProviderConnectionState,
    TriageRunResult,
    WorkspaceSettings,
)
from inboxanchor.sender_intelligence import (
    observe_profile_email,
    sender_address,
    sender_domain,
)


class InboxRepository:
    def __init__(self, session):
        self.session = session

    def _run_email_details_query(
        self,
        run_id: str,
        *,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        q: Optional[str] = None,
        unread_only: bool = False,
        time_range: Optional[str] = None,
    ):
        query = (
            self.session.query(EmailRecordORM, ClassificationORM)
            .join(
                ClassificationORM,
                and_(
                    ClassificationORM.run_id == EmailRecordORM.run_id,
                    ClassificationORM.email_id == EmailRecordORM.email_id,
                ),
            )
            .filter(EmailRecordORM.run_id == run_id)
        )
        if priority:
            query = query.filter(ClassificationORM.priority == priority)
        if category:
            query = query.filter(ClassificationORM.category == category)
        if unread_only:
            query = query.filter(EmailRecordORM.unread.is_(True))
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(EmailRecordORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(EmailRecordORM.received_at < window.end_at)
        if q:
            pattern = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    EmailRecordORM.subject.ilike(pattern),
                    EmailRecordORM.sender.ilike(pattern),
                    EmailRecordORM.snippet.ilike(pattern),
                    EmailRecordORM.body_preview.ilike(pattern),
                )
            )
        return query

    @staticmethod
    def _mailbox_email_payload(row: MailboxEmailORM) -> dict:
        return {
            "provider": row.provider,
            "email_id": row.email_id,
            "thread_id": row.thread_id,
            "sender": row.sender,
            "subject": row.subject,
            "snippet": row.snippet,
            "body_preview": row.body_preview,
            "body_full": row.body_full,
            "received_at": row.received_at.isoformat(),
            "labels": row.labels,
            "has_attachments": row.has_attachments,
            "unread": row.unread,
            "last_synced_at": row.last_synced_at.isoformat(),
        }

    @staticmethod
    def _mailbox_classification_payload(row: MailboxClassificationORM) -> dict:
        return {
            "email_id": row.email_id,
            "classification": {
                "category": row.category,
                "priority": row.priority,
                "confidence": row.confidence,
                "reason": row.reason,
            },
            "source": row.source,
            "run_id": row.run_id,
            "updated_at": row.updated_at.isoformat(),
        }

    @staticmethod
    def _mailbox_action_item_payload(row: MailboxActionItemORM) -> dict:
        return {
            "email_id": row.email_id,
            "action_type": row.action_type,
            "description": row.description,
            "due_hint": row.due_hint,
            "requires_reply": row.requires_reply,
            "source": row.source,
            "run_id": row.run_id,
            "updated_at": row.updated_at.isoformat(),
        }

    @staticmethod
    def _mailbox_recommendation_payload(row: MailboxRecommendationORM) -> dict:
        return {
            "email_id": row.email_id,
            "recommended_action": row.recommended_action,
            "reason": row.reason,
            "confidence": row.confidence,
            "status": row.status,
            "requires_approval": row.requires_approval,
            "blocked_reason": row.blocked_reason,
            "proposed_labels": row.proposed_labels,
            "source": row.source,
            "run_id": row.run_id,
            "updated_at": row.updated_at.isoformat(),
        }

    @staticmethod
    def _sender_profile_payload(row: SenderProfileORM) -> dict:
        payload = dict(row.payload or {})
        payload["provider"] = row.provider
        payload["sender_address"] = row.sender_address
        return payload

    @staticmethod
    def _domain_profile_payload(row: DomainProfileORM) -> dict:
        payload = dict(row.payload or {})
        payload["provider"] = row.provider
        payload["domain"] = row.domain
        return payload

    @staticmethod
    def _reminder_model(row: FollowUpReminderORM) -> FollowUpReminder:
        return FollowUpReminder(
            id=row.id,
            provider=row.provider,
            email_id=row.email_id,
            owner_email=row.owner_email,
            thread_id=row.thread_id,
            run_id=row.run_id,
            sender=row.sender,
            subject=row.subject,
            preview=row.preview,
            priority=row.priority,
            category=row.category,
            note=row.note,
            source=row.source,
            due_at=row.due_at,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
        )

    @staticmethod
    def _alias_model(row: EmailAliasORM) -> EmailAlias:
        return EmailAlias(
            id=row.id,
            owner_email=row.owner_email,
            provider=row.provider,
            alias_address=row.alias_address,
            target_email=row.target_email,
            alias_type=row.alias_type,
            label=row.label,
            purpose=row.purpose,
            note=row.note,
            status=row.status,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
        )

    def save_run(
        self,
        result: TriageRunResult,
        *,
        persisted_emails=None,
        persisted_classifications=None,
        persisted_action_items=None,
        persisted_recommendations=None,
    ) -> None:
        emails = persisted_emails or result.emails
        classifications = persisted_classifications or result.classifications
        action_items = persisted_action_items or result.action_items
        recommendations = persisted_recommendations or result.recommendations

        run = TriageRunORM(
            run_id=result.run_id,
            provider=result.provider,
            dry_run=result.dry_run,
            total_emails=result.total_emails,
            digest_summary=result.digest.summary,
            approvals_required=result.approvals_required,
            blocked_actions=result.blocked_actions,
            raw_payload=result.model_dump(mode="json"),
        )
        self.session.add(run)

        for email in emails:
            self.upsert_mailbox_email(result.provider, email)
            self.session.add(
                EmailRecordORM(
                    run_id=result.run_id,
                    email_id=email.id,
                    thread_id=email.thread_id,
                    sender=email.sender,
                    subject=email.subject,
                    snippet=email.snippet,
                    body_preview=email.body_preview,
                    received_at=email.received_at,
                    labels=email.labels,
                    has_attachments=email.has_attachments,
                    unread=email.unread,
                )
            )

            classification = classifications[email.id]
            self.session.add(
                ClassificationORM(
                    run_id=result.run_id,
                    email_id=email.id,
                    category=classification.category,
                    priority=classification.priority,
                    confidence=classification.confidence,
                    reason=classification.reason,
                )
            )
            self.upsert_mailbox_classification(
                result.provider,
                email.id,
                classification,
                source="run",
                run_id=result.run_id,
            )
            self.replace_mailbox_action_items(
                result.provider,
                email.id,
                action_items.get(email.id, []),
                source="run",
                run_id=result.run_id,
            )

            for action_item in action_items.get(email.id, []):
                self.session.add(
                    ActionItemORM(
                        run_id=result.run_id,
                        email_id=email.id,
                        action_type=action_item.action_type,
                        description=action_item.description,
                        due_hint=action_item.due_hint,
                        requires_reply=action_item.requires_reply,
                    )
                )

        for recommendation in recommendations:
            self.session.add(
                RecommendationORM(
                    run_id=result.run_id,
                    email_id=recommendation.email_id,
                    recommended_action=recommendation.recommended_action,
                    reason=recommendation.reason,
                    confidence=recommendation.confidence,
                    status=recommendation.status,
                    requires_approval=recommendation.requires_approval,
                    blocked_reason=recommendation.blocked_reason,
                    proposed_labels=recommendation.proposed_labels,
                )
            )
            self.upsert_mailbox_recommendation(
                result.provider,
                recommendation.email_id,
                recommendation,
                source="run",
                run_id=result.run_id,
            )

    def get_run(self, run_id: str) -> Optional[dict]:
        run = self.session.get(TriageRunORM, run_id)
        return run.raw_payload if run else None

    def get_latest_run_id(self, provider: Optional[str] = None) -> Optional[str]:
        query = self.session.query(TriageRunORM)
        if provider:
            query = query.filter(TriageRunORM.provider == provider)
        row = query.order_by(TriageRunORM.started_at.desc()).first()
        return row.run_id if row else None

    def get_sender_profile(self, provider: str, sender: str) -> Optional[dict]:
        address = sender_address(sender)
        if not address:
            return None
        row = (
            self.session.query(SenderProfileORM)
            .filter(
                SenderProfileORM.provider == provider,
                SenderProfileORM.sender_address == address,
            )
            .first()
        )
        return self._sender_profile_payload(row) if row else None

    def get_domain_profile(self, provider: str, domain: str) -> Optional[dict]:
        normalized = (domain or "").strip().lower()
        if not normalized:
            return None
        row = (
            self.session.query(DomainProfileORM)
            .filter(
                DomainProfileORM.provider == provider,
                DomainProfileORM.domain == normalized,
            )
            .first()
        )
        return self._domain_profile_payload(row) if row else None

    def _observe_sender_intelligence(self, provider: str, email, *, count_message: bool) -> None:
        address = sender_address(email.sender)
        domain = sender_domain(email.sender)
        if address:
            sender_row = (
                self.session.query(SenderProfileORM)
                .filter(
                    SenderProfileORM.provider == provider,
                    SenderProfileORM.sender_address == address,
                )
                .first()
            )
            sender_payload = observe_profile_email(
                self._sender_profile_payload(sender_row) if sender_row else None,
                provider=provider,
                email=email,
                profile_kind="sender",
                count_message=count_message,
            )
            if sender_row is None:
                self.session.add(
                    SenderProfileORM(
                        provider=provider,
                        sender_address=address,
                        payload=sender_payload,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            else:
                sender_row.payload = sender_payload
                sender_row.updated_at = datetime.now(timezone.utc)

        if domain:
            domain_row = (
                self.session.query(DomainProfileORM)
                .filter(
                    DomainProfileORM.provider == provider,
                    DomainProfileORM.domain == domain,
                )
                .first()
            )
            domain_payload = observe_profile_email(
                self._domain_profile_payload(domain_row) if domain_row else None,
                provider=provider,
                email=email,
                profile_kind="domain",
                count_message=count_message,
            )
            if domain_row is None:
                self.session.add(
                    DomainProfileORM(
                        provider=provider,
                        domain=domain,
                        payload=domain_payload,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            else:
                domain_row.payload = domain_payload
                domain_row.updated_at = datetime.now(timezone.utc)

    def upsert_mailbox_email(self, provider: str, email) -> None:
        row = (
            self.session.query(MailboxEmailORM)
            .filter(
                MailboxEmailORM.provider == provider,
                MailboxEmailORM.email_id == email.id,
            )
            .first()
        )
        incoming_body_full = getattr(email, "body_full", None)
        if incoming_body_full is None:
            incoming_body_full = email.body_preview or email.snippet
        body_full = (
            normalize_email_body_text(incoming_body_full)
            if isinstance(incoming_body_full, str)
            else ""
        )
        if (
            not body_full
            and (email.body_preview or "").strip()
            and email.body_preview != email.snippet
        ):
            body_full = normalize_email_body_text(email.body_preview)
        body_preview = normalize_email_body_text(email.body_preview or email.snippet)
        if row is not None and not body_full and row.body_full:
            body_full = row.body_full
        payload = {
            "thread_id": email.thread_id,
            "sender": email.sender,
            "subject": email.subject,
            "snippet": email.snippet,
            "body_preview": body_preview,
            "body_full": body_full,
            "received_at": email.received_at,
            "labels": email.labels,
            "has_attachments": email.has_attachments,
            "unread": email.unread,
            "last_synced_at": datetime.now(timezone.utc),
        }

        if row is None:
            self._observe_sender_intelligence(provider, email, count_message=True)
            self.session.add(
                MailboxEmailORM(
                    provider=provider,
                    email_id=email.id,
                    **payload,
                )
            )
            return

        row.thread_id = payload["thread_id"]
        row.sender = payload["sender"]
        row.subject = payload["subject"]
        row.snippet = payload["snippet"]
        row.body_preview = payload["body_preview"]
        row.body_full = payload["body_full"]
        row.received_at = payload["received_at"]
        row.labels = payload["labels"]
        row.has_attachments = payload["has_attachments"]
        row.unread = payload["unread"]
        row.last_synced_at = payload["last_synced_at"]
        self._observe_sender_intelligence(provider, email, count_message=False)

    def upsert_mailbox_classification(
        self,
        provider: str,
        email_id: str,
        classification: EmailClassification,
        *,
        source: str = "heuristic",
        run_id: Optional[str] = None,
    ) -> dict:
        row = (
            self.session.query(MailboxClassificationORM)
            .filter(
                MailboxClassificationORM.provider == provider,
                MailboxClassificationORM.email_id == email_id,
            )
            .first()
        )
        payload = {
            "category": getattr(classification.category, "value", classification.category),
            "priority": getattr(classification.priority, "value", classification.priority),
            "confidence": float(classification.confidence),
            "reason": classification.reason,
            "source": source,
            "run_id": run_id,
            "updated_at": datetime.now(timezone.utc),
        }
        if row is None:
            row = MailboxClassificationORM(
                provider=provider,
                email_id=email_id,
                **payload,
            )
            self.session.add(row)
        else:
            row.category = payload["category"]
            row.priority = payload["priority"]
            row.confidence = payload["confidence"]
            row.reason = payload["reason"]
            row.source = payload["source"]
            row.run_id = payload["run_id"]
            row.updated_at = payload["updated_at"]
        self.session.flush()
        return self._mailbox_classification_payload(row)

    def replace_mailbox_action_items(
        self,
        provider: str,
        email_id: str,
        items: list[EmailActionItem],
        *,
        source: str = "heuristic",
        run_id: Optional[str] = None,
    ) -> list[dict]:
        (
            self.session.query(MailboxActionItemORM)
            .filter(
                MailboxActionItemORM.provider == provider,
                MailboxActionItemORM.email_id == email_id,
            )
            .delete(synchronize_session=False)
        )
        rows: list[MailboxActionItemORM] = []
        timestamp = datetime.now(timezone.utc)
        for item in items:
            row = MailboxActionItemORM(
                provider=provider,
                email_id=email_id,
                action_type=item.action_type,
                description=item.description,
                due_hint=item.due_hint,
                requires_reply=item.requires_reply,
                source=source,
                run_id=run_id,
                updated_at=timestamp,
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return [self._mailbox_action_item_payload(row) for row in rows]

    def upsert_mailbox_recommendation(
        self,
        provider: str,
        email_id: str,
        recommendation: EmailRecommendation,
        *,
        source: str = "heuristic",
        run_id: Optional[str] = None,
    ) -> dict:
        row = (
            self.session.query(MailboxRecommendationORM)
            .filter(
                MailboxRecommendationORM.provider == provider,
                MailboxRecommendationORM.email_id == email_id,
            )
            .first()
        )
        payload = {
            "recommended_action": recommendation.recommended_action,
            "reason": recommendation.reason,
            "confidence": float(recommendation.confidence),
            "status": getattr(recommendation.status, "value", recommendation.status),
            "requires_approval": recommendation.requires_approval,
            "blocked_reason": recommendation.blocked_reason,
            "proposed_labels": list(recommendation.proposed_labels),
            "source": source,
            "run_id": run_id,
            "updated_at": datetime.now(timezone.utc),
        }
        if row is None:
            row = MailboxRecommendationORM(
                provider=provider,
                email_id=email_id,
                **payload,
            )
            self.session.add(row)
        else:
            row.recommended_action = payload["recommended_action"]
            row.reason = payload["reason"]
            row.confidence = payload["confidence"]
            row.status = payload["status"]
            row.requires_approval = payload["requires_approval"]
            row.blocked_reason = payload["blocked_reason"]
            row.proposed_labels = payload["proposed_labels"]
            row.source = payload["source"]
            row.run_id = payload["run_id"]
            row.updated_at = payload["updated_at"]
        self.session.flush()
        return self._mailbox_recommendation_payload(row)

    def get_mailbox_classification_map(
        self,
        provider: str,
        email_ids: list[str],
    ) -> dict[str, dict]:
        if not email_ids:
            return {}
        rows = (
            self.session.query(MailboxClassificationORM)
            .filter(
                MailboxClassificationORM.provider == provider,
                MailboxClassificationORM.email_id.in_(email_ids),
            )
            .all()
        )
        return {
            row.email_id: self._mailbox_classification_payload(row)
            for row in rows
        }

    def get_mailbox_action_items(
        self,
        provider: str,
        email_id: str,
    ) -> list[dict]:
        rows = (
            self.session.query(MailboxActionItemORM)
            .filter(
                MailboxActionItemORM.provider == provider,
                MailboxActionItemORM.email_id == email_id,
            )
            .order_by(MailboxActionItemORM.id.asc())
            .all()
        )
        return [self._mailbox_action_item_payload(row) for row in rows]

    def count_mailbox_action_items(
        self,
        provider: str,
        *,
        unread_only: Optional[bool] = None,
        time_range: Optional[str] = None,
    ) -> int:
        query = (
            self.session.query(MailboxActionItemORM)
            .join(
                MailboxEmailORM,
                and_(
                    MailboxEmailORM.provider == MailboxActionItemORM.provider,
                    MailboxEmailORM.email_id == MailboxActionItemORM.email_id,
                ),
            )
            .filter(MailboxActionItemORM.provider == provider)
        )
        if unread_only is True:
            query = query.filter(MailboxEmailORM.unread.is_(True))
        elif unread_only is False:
            query = query.filter(MailboxEmailORM.unread.is_(False))
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(MailboxEmailORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(MailboxEmailORM.received_at < window.end_at)
        return query.count()

    def get_mailbox_recommendation_map(
        self,
        provider: str,
        email_ids: list[str],
    ) -> dict[str, dict]:
        if not email_ids:
            return {}
        rows = (
            self.session.query(MailboxRecommendationORM)
            .filter(
                MailboxRecommendationORM.provider == provider,
                MailboxRecommendationORM.email_id.in_(email_ids),
            )
            .all()
        )
        return {
            row.email_id: self._mailbox_recommendation_payload(row)
            for row in rows
        }

    def get_mailbox_recommendation_detail(
        self,
        provider: str,
        email_id: str,
    ) -> Optional[dict]:
        row = (
            self.session.query(MailboxRecommendationORM)
            .filter(
                MailboxRecommendationORM.provider == provider,
                MailboxRecommendationORM.email_id == email_id,
            )
            .first()
        )
        return self._mailbox_recommendation_payload(row) if row else None

    def get_mailbox_classification_detail(
        self,
        provider: str,
        email_id: str,
    ) -> Optional[dict]:
        row = (
            self.session.query(MailboxClassificationORM)
            .filter(
                MailboxClassificationORM.provider == provider,
                MailboxClassificationORM.email_id == email_id,
            )
            .first()
        )
        return self._mailbox_classification_payload(row) if row else None

    def list_mailbox_classifications(
        self,
        provider: str,
        *,
        unread_only: Optional[bool] = None,
        q: Optional[str] = None,
        time_range: Optional[str] = None,
    ) -> dict[str, dict]:
        query = (
            self.session.query(MailboxClassificationORM, MailboxEmailORM)
            .join(
                MailboxEmailORM,
                and_(
                    MailboxEmailORM.provider == MailboxClassificationORM.provider,
                    MailboxEmailORM.email_id == MailboxClassificationORM.email_id,
                ),
            )
            .filter(MailboxClassificationORM.provider == provider)
        )
        if unread_only is True:
            query = query.filter(MailboxEmailORM.unread.is_(True))
        elif unread_only is False:
            query = query.filter(MailboxEmailORM.unread.is_(False))
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(MailboxEmailORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(MailboxEmailORM.received_at < window.end_at)
        if q:
            pattern = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    MailboxEmailORM.subject.ilike(pattern),
                    MailboxEmailORM.sender.ilike(pattern),
                    MailboxEmailORM.snippet.ilike(pattern),
                    MailboxEmailORM.body_preview.ilike(pattern),
                )
            )
        rows = query.order_by(MailboxEmailORM.received_at.desc()).all()
        payload: dict[str, dict] = {}
        for classification, _mailbox_email in rows:
            payload[classification.email_id] = self._mailbox_classification_payload(classification)
        return payload

    def get_mailbox_classification_stats(
        self,
        provider: str,
        *,
        unread_only: Optional[bool] = None,
        time_range: Optional[str] = None,
        high_priority_limit: int = 250,
    ) -> dict:
        query = (
            self.session.query(MailboxClassificationORM, MailboxEmailORM)
            .join(
                MailboxEmailORM,
                and_(
                    MailboxEmailORM.provider == MailboxClassificationORM.provider,
                    MailboxEmailORM.email_id == MailboxClassificationORM.email_id,
                ),
            )
            .filter(MailboxClassificationORM.provider == provider)
        )
        if unread_only is True:
            query = query.filter(MailboxEmailORM.unread.is_(True))
        elif unread_only is False:
            query = query.filter(MailboxEmailORM.unread.is_(False))
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(MailboxEmailORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(MailboxEmailORM.received_at < window.end_at)
        rows = query.all()
        category_counts: dict[str, int] = {}
        high_priority_ids: list[tuple[datetime, str]] = []
        for classification, mailbox_email in rows:
            category_counts[classification.category] = (
                category_counts.get(classification.category, 0) + 1
            )
            if classification.priority in {"critical", "high"}:
                high_priority_ids.append((mailbox_email.received_at, mailbox_email.email_id))
        high_priority_ids.sort(reverse=True)
        return {
            "category_counts": category_counts,
            "high_priority_ids": [
                email_id for _received_at, email_id in high_priority_ids[:high_priority_limit]
            ],
        }

    def get_mailbox_recommendation_stats(
        self,
        provider: str,
        *,
        unread_only: Optional[bool] = None,
        time_range: Optional[str] = None,
    ) -> dict:
        query = (
            self.session.query(MailboxRecommendationORM, MailboxEmailORM)
            .join(
                MailboxEmailORM,
                and_(
                    MailboxEmailORM.provider == MailboxRecommendationORM.provider,
                    MailboxEmailORM.email_id == MailboxRecommendationORM.email_id,
                ),
            )
            .filter(MailboxRecommendationORM.provider == provider)
        )
        if unread_only is True:
            query = query.filter(MailboxEmailORM.unread.is_(True))
        elif unread_only is False:
            query = query.filter(MailboxEmailORM.unread.is_(False))
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(MailboxEmailORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(MailboxEmailORM.received_at < window.end_at)
        rows = query.all()
        safe_count = 0
        review_count = 0
        blocked_count = 0
        auto_label_candidates = 0
        for recommendation, _mailbox_email in rows:
            if recommendation.status == "safe":
                safe_count += 1
            elif recommendation.status == "requires_approval":
                review_count += 1
            elif recommendation.status == "blocked":
                blocked_count += 1
            if recommendation.proposed_labels:
                auto_label_candidates += 1
        return {
            "safe_count": safe_count,
            "review_count": review_count,
            "blocked_count": blocked_count,
            "auto_label_candidates": auto_label_candidates,
        }

    def save_mailbox_email_body(
        self,
        provider: str,
        email_id: str,
        *,
        body_full: str,
        body_preview: Optional[str] = None,
    ) -> Optional[dict]:
        row = (
            self.session.query(MailboxEmailORM)
            .filter(
                MailboxEmailORM.provider == provider,
                MailboxEmailORM.email_id == email_id,
            )
            .first()
        )
        if row is None:
            return None
        normalized_body = normalize_email_body_text(body_full or "")
        row.body_full = normalized_body
        if body_preview is not None:
            row.body_preview = normalize_email_body_text(body_preview)
        elif normalized_body:
            row.body_preview = normalized_body[:500]
        row.last_synced_at = datetime.now(timezone.utc)
        self.session.flush()
        return self._mailbox_email_payload(row)

    def update_mailbox_email_state(
        self,
        provider: str,
        email_id: str,
        *,
        unread: Optional[bool] = None,
        labels_to_add: Optional[list[str]] = None,
        labels_to_remove: Optional[list[str]] = None,
    ) -> Optional[dict]:
        row = (
            self.session.query(MailboxEmailORM)
            .filter(
                MailboxEmailORM.provider == provider,
                MailboxEmailORM.email_id == email_id,
            )
            .first()
        )
        if row is None:
            return None
        if unread is not None:
            row.unread = unread
        labels = [str(label) for label in row.labels]
        if labels_to_add:
            labels.extend(str(label) for label in labels_to_add if label)
        if labels_to_remove:
            remove_set = {str(label) for label in labels_to_remove}
            labels = [label for label in labels if label not in remove_set]
        row.labels = list(dict.fromkeys(labels))
        row.last_synced_at = datetime.now(timezone.utc)
        self.session.flush()
        return self._mailbox_email_payload(row)

    def reconcile_unread_working_set(
        self,
        provider: str,
        *,
        unread_email_ids: list[str],
        time_range: Optional[str] = None,
    ) -> int:
        query = self.session.query(MailboxEmailORM).filter(MailboxEmailORM.provider == provider)
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(MailboxEmailORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(MailboxEmailORM.received_at < window.end_at)
        rows = query.filter(MailboxEmailORM.unread.is_(True)).all()
        unread_set = {str(email_id) for email_id in unread_email_ids}
        updated = 0
        for row in rows:
            if row.email_id in unread_set:
                continue
            row.unread = False
            row.last_synced_at = datetime.now(timezone.utc)
            updated += 1
        self.session.flush()
        return updated

    def remove_labels_from_run_emails(
        self,
        run_id: str,
        labels: list[str],
        *,
        email_ids: Optional[list[str]] = None,
    ) -> int:
        if not labels:
            return 0
        label_set = set(labels)
        query = self.session.query(EmailRecordORM).filter(EmailRecordORM.run_id == run_id)
        if email_ids:
            query = query.filter(EmailRecordORM.email_id.in_(email_ids))
        rows = query.all()
        updated = 0
        for row in rows:
            next_labels = [label for label in row.labels if label not in label_set]
            if next_labels == row.labels:
                continue
            row.labels = next_labels
            updated += 1
        self.session.flush()
        return updated

    def remove_labels_from_mailbox(
        self,
        provider: str,
        labels: list[str],
        *,
        email_ids: Optional[list[str]] = None,
    ) -> int:
        if not labels:
            return 0
        label_set = set(labels)
        query = self.session.query(MailboxEmailORM).filter(MailboxEmailORM.provider == provider)
        if email_ids:
            query = query.filter(MailboxEmailORM.email_id.in_(email_ids))
        rows = query.all()
        updated = 0
        for row in rows:
            next_labels = [label for label in row.labels if label not in label_set]
            if next_labels == row.labels:
                continue
            row.labels = next_labels
            updated += 1
        self.session.flush()
        return updated

    def get_mailbox_email(self, provider: str, email_id: str) -> Optional[dict]:
        row = (
            self.session.query(MailboxEmailORM)
            .filter(
                MailboxEmailORM.provider == provider,
                MailboxEmailORM.email_id == email_id,
            )
            .first()
        )
        if row is None:
            return None
        return self._mailbox_email_payload(row)

    def get_mailbox_email_map(self, provider: str, email_ids: list[str]) -> dict[str, dict]:
        if not email_ids:
            return {}
        rows = (
            self.session.query(MailboxEmailORM)
            .filter(
                MailboxEmailORM.provider == provider,
                MailboxEmailORM.email_id.in_(email_ids),
            )
            .all()
        )
        return {row.email_id: self._mailbox_email_payload(row) for row in rows}

    def count_mailbox_emails(
        self,
        provider: str,
        *,
        unread_only: Optional[bool] = None,
        hydrated_only: bool = False,
        has_attachments: Optional[bool] = None,
        q: Optional[str] = None,
        time_range: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
    ) -> int:
        query = self.session.query(MailboxEmailORM).filter(MailboxEmailORM.provider == provider)
        if priority or category:
            query = query.join(
                MailboxClassificationORM,
                and_(
                    MailboxClassificationORM.provider == MailboxEmailORM.provider,
                    MailboxClassificationORM.email_id == MailboxEmailORM.email_id,
                ),
            )
            if priority:
                query = query.filter(MailboxClassificationORM.priority == priority)
            if category:
                query = query.filter(MailboxClassificationORM.category == category)
        if unread_only is True:
            query = query.filter(MailboxEmailORM.unread.is_(True))
        elif unread_only is False:
            query = query.filter(MailboxEmailORM.unread.is_(False))
        if has_attachments is True:
            query = query.filter(MailboxEmailORM.has_attachments.is_(True))
        elif has_attachments is False:
            query = query.filter(MailboxEmailORM.has_attachments.is_(False))
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(MailboxEmailORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(MailboxEmailORM.received_at < window.end_at)
        if q:
            pattern = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    MailboxEmailORM.subject.ilike(pattern),
                    MailboxEmailORM.sender.ilike(pattern),
                    MailboxEmailORM.snippet.ilike(pattern),
                    MailboxEmailORM.body_preview.ilike(pattern),
                )
            )
        if hydrated_only:
            query = query.filter(func.length(func.trim(MailboxEmailORM.body_full)) > 0)
        return query.count()

    def list_mailbox_emails(
        self,
        provider: str,
        *,
        limit: int = 50,
        offset: int = 0,
        unread_only: Optional[bool] = None,
        q: Optional[str] = None,
        time_range: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[dict]:
        query = self.session.query(MailboxEmailORM).filter(MailboxEmailORM.provider == provider)
        if priority or category:
            query = query.join(
                MailboxClassificationORM,
                and_(
                    MailboxClassificationORM.provider == MailboxEmailORM.provider,
                    MailboxClassificationORM.email_id == MailboxEmailORM.email_id,
                ),
            )
            if priority:
                query = query.filter(MailboxClassificationORM.priority == priority)
            if category:
                query = query.filter(MailboxClassificationORM.category == category)
        if unread_only is True:
            query = query.filter(MailboxEmailORM.unread.is_(True))
        elif unread_only is False:
            query = query.filter(MailboxEmailORM.unread.is_(False))
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(MailboxEmailORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(MailboxEmailORM.received_at < window.end_at)
        if q:
            pattern = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    MailboxEmailORM.subject.ilike(pattern),
                    MailboxEmailORM.sender.ilike(pattern),
                    MailboxEmailORM.snippet.ilike(pattern),
                    MailboxEmailORM.body_preview.ilike(pattern),
                )
            )
        rows = (
            query.order_by(MailboxEmailORM.received_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [self._mailbox_email_payload(row) for row in rows]

    def get_latest_classification_map(
        self,
        provider: str,
        email_ids: list[str],
    ) -> dict[str, dict]:
        if not email_ids:
            return {}
        rows = (
            self.session.query(ClassificationORM, EmailRecordORM, TriageRunORM)
            .join(
                EmailRecordORM,
                and_(
                    EmailRecordORM.run_id == ClassificationORM.run_id,
                    EmailRecordORM.email_id == ClassificationORM.email_id,
                ),
            )
            .join(TriageRunORM, TriageRunORM.run_id == ClassificationORM.run_id)
            .filter(
                TriageRunORM.provider == provider,
                EmailRecordORM.email_id.in_(email_ids),
            )
            .order_by(EmailRecordORM.email_id.asc(), TriageRunORM.started_at.desc())
            .all()
        )
        payload: dict[str, dict] = {}
        for classification, email, run in rows:
            if email.email_id in payload:
                continue
            payload[email.email_id] = {
                "email_id": email.email_id,
                "classification": {
                    "category": classification.category,
                    "priority": classification.priority,
                    "confidence": classification.confidence,
                    "reason": classification.reason,
                },
                "run_id": run.run_id,
            }
        return payload

    def get_latest_classification_detail(
        self,
        provider: str,
        email_id: str,
    ) -> Optional[dict]:
        details = self.get_latest_classification_map(provider, [email_id])
        return details.get(email_id)

    def get_mailbox_cache_stats(self, provider: str, *, time_range: Optional[str] = None) -> dict:
        query = self.session.query(MailboxEmailORM).filter(MailboxEmailORM.provider == provider)
        if time_range:
            window = resolve_time_window(time_range)
            if window.start_at is not None:
                query = query.filter(MailboxEmailORM.received_at >= window.start_at)
            if window.end_at is not None:
                query = query.filter(MailboxEmailORM.received_at < window.end_at)
        cached_count = query.count()
        unread_count = query.filter(MailboxEmailORM.unread.is_(True)).count()
        hydrated_count = query.filter(func.length(func.trim(MailboxEmailORM.body_full)) > 0).count()
        oldest = query.order_by(MailboxEmailORM.received_at.asc()).first()
        newest = query.order_by(MailboxEmailORM.received_at.desc()).first()
        return {
            "cached_count": cached_count,
            "cached_unread_count": unread_count,
            "hydrated_count": hydrated_count,
            "oldest_cached_at": oldest.received_at.isoformat() if oldest else None,
            "newest_cached_at": newest.received_at.isoformat() if newest else None,
        }

    def list_runs(self, limit: int = 25) -> list[dict]:
        rows = (
            self.session.query(TriageRunORM)
            .order_by(TriageRunORM.started_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "run_id": row.run_id,
                "provider": row.provider,
                "dry_run": row.dry_run,
                "total_emails": row.total_emails,
                "scanned_emails": row.raw_payload.get("scanned_emails", row.total_emails),
                "batch_count": row.raw_payload.get("batch_count", 1),
                "digest_summary": row.digest_summary,
                "approvals_required": row.approvals_required,
                "blocked_actions": row.blocked_actions,
                "email_preview_limit": row.raw_payload.get("email_preview_limit"),
                "recommendation_preview_limit": row.raw_payload.get(
                    "recommendation_preview_limit"
                ),
                "email_preview_truncated": row.raw_payload.get(
                    "email_preview_truncated",
                    False,
                ),
                "recommendation_preview_truncated": row.raw_payload.get(
                    "recommendation_preview_truncated",
                    False,
                ),
                "started_at": row.started_at.isoformat(),
            }
            for row in rows
        ]

    def get_workspace_settings(self) -> WorkspaceSettings:
        row = self.session.get(WorkspaceSettingsORM, "default")
        if not row or not row.payload:
            return WorkspaceSettings()
        return WorkspaceSettings.model_validate(row.payload)

    def save_workspace_settings(self, settings: WorkspaceSettings) -> WorkspaceSettings:
        payload = settings.model_copy(update={"updated_at": settings.updated_at}).model_dump(
            mode="json"
        )
        row = self.session.get(WorkspaceSettingsORM, "default")
        if row is None:
            row = WorkspaceSettingsORM(workspace_id="default", payload=payload)
            self.session.add(row)
        else:
            row.payload = payload
        return WorkspaceSettings.model_validate(payload)

    def get_provider_connection(self, provider: str) -> ProviderConnectionState:
        row = self.session.get(ProviderConnectionORM, provider)
        if not row or not row.payload:
            return ProviderConnectionState(provider=provider)
        return ProviderConnectionState.model_validate(row.payload)

    def save_provider_connection(
        self,
        state: ProviderConnectionState,
    ) -> ProviderConnectionState:
        payload = state.model_dump(mode="json")
        row = self.session.get(ProviderConnectionORM, state.provider)
        if row is None:
            row = ProviderConnectionORM(provider=state.provider, payload=payload)
            self.session.add(row)
        else:
            row.payload = payload
        return ProviderConnectionState.model_validate(payload)

    def list_provider_connections(self, providers: Optional[list[str]] = None) -> list[dict]:
        query = self.session.query(ProviderConnectionORM)
        if providers:
            query = query.filter(ProviderConnectionORM.provider.in_(providers))
        rows = query.order_by(ProviderConnectionORM.provider.asc()).all()
        return [
            ProviderConnectionState.model_validate(row.payload).model_dump(mode="json")
            for row in rows
        ]

    def get_checkpoint(self, provider_name: str) -> Optional[str]:
        row = self.session.get(ProviderCheckpointORM, provider_name)
        return row.checkpoint_value if row else None

    def save_checkpoint(self, provider_name: str, checkpoint_value: str) -> None:
        row = self.session.get(ProviderCheckpointORM, provider_name)
        if row is None:
            row = ProviderCheckpointORM(
                provider=provider_name,
                checkpoint_value=checkpoint_value,
            )
            self.session.add(row)
        else:
            row.checkpoint_value = checkpoint_value
            row.updated_at = datetime.now(timezone.utc)

    def get_provider_sync_state(self, provider_name: str, sync_kind: str) -> Optional[dict]:
        row = (
            self.session.query(ProviderSyncStateORM)
            .filter(
                ProviderSyncStateORM.provider == provider_name,
                ProviderSyncStateORM.sync_kind == sync_kind,
            )
            .first()
        )
        if row is None:
            return None
        payload = self._normalize_provider_sync_payload(dict(row.payload or {}))
        payload.setdefault("provider", provider_name)
        payload.setdefault("sync_kind", sync_kind)
        payload["updated_at"] = row.updated_at.isoformat()
        return payload

    def save_provider_sync_state(
        self,
        provider_name: str,
        sync_kind: str,
        payload: dict,
    ) -> dict:
        row = (
            self.session.query(ProviderSyncStateORM)
            .filter(
                ProviderSyncStateORM.provider == provider_name,
                ProviderSyncStateORM.sync_kind == sync_kind,
            )
            .first()
        )
        normalized = self._normalize_provider_sync_payload(dict(payload))
        normalized.setdefault("provider", provider_name)
        normalized.setdefault("sync_kind", sync_kind)
        if row is None:
            row = ProviderSyncStateORM(
                provider=provider_name,
                sync_kind=sync_kind,
                payload=normalized,
            )
            self.session.add(row)
        else:
            row.payload = normalized
            row.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        stored = dict(normalized)
        stored["updated_at"] = row.updated_at.isoformat()
        return stored

    @staticmethod
    def _normalize_provider_sync_payload(payload: dict) -> dict:
        normalized = dict(payload)
        processed_count = int(normalized.get("processed_count") or 0)
        next_offset = int(normalized.get("next_offset") or processed_count)
        if next_offset < processed_count:
            next_offset = processed_count
        target_count = int(normalized.get("target_count") or 0)
        if target_count and processed_count > target_count:
            target_count = processed_count
        normalized["processed_count"] = processed_count
        normalized["next_offset"] = next_offset
        if target_count:
            normalized["target_count"] = target_count
        return normalized

    def clear_provider_sync_state(self, provider_name: str, sync_kind: str) -> None:
        row = (
            self.session.query(ProviderSyncStateORM)
            .filter(
                ProviderSyncStateORM.provider == provider_name,
                ProviderSyncStateORM.sync_kind == sync_kind,
            )
            .first()
        )
        if row is not None:
            self.session.delete(row)

    def list_email_aliases(
        self,
        *,
        owner_email: str,
        status: Optional[str] = None,
    ) -> list[EmailAlias]:
        query = self.session.query(EmailAliasORM).filter(
            EmailAliasORM.owner_email == owner_email
        )
        if status:
            query = query.filter(EmailAliasORM.status == status)
        rows = query.order_by(EmailAliasORM.created_at.desc()).all()
        return [self._alias_model(row) for row in rows]

    def create_email_alias(self, alias: EmailAlias) -> EmailAlias:
        row = EmailAliasORM(
            owner_email=alias.owner_email,
            provider=alias.provider,
            alias_address=alias.alias_address,
            target_email=alias.target_email,
            alias_type=alias.alias_type,
            label=alias.label,
            purpose=alias.purpose,
            note=alias.note,
            status=alias.status,
            created_at=alias.created_at,
            revoked_at=alias.revoked_at,
        )
        self.session.add(row)
        self.session.flush()
        return self._alias_model(row)

    def get_email_alias(self, alias_id: int) -> Optional[EmailAlias]:
        row = self.session.get(EmailAliasORM, alias_id)
        if row is None:
            return None
        return self._alias_model(row)

    def get_email_alias_by_address(self, alias_address: str) -> Optional[EmailAlias]:
        row = (
            self.session.query(EmailAliasORM)
            .filter(EmailAliasORM.alias_address == alias_address.strip().lower())
            .order_by(EmailAliasORM.created_at.desc())
            .first()
        )
        if row is None:
            return None
        return self._alias_model(row)

    def revoke_email_alias(self, alias_id: int) -> Optional[EmailAlias]:
        row = self.session.get(EmailAliasORM, alias_id)
        if row is None:
            return None
        row.status = EmailAliasStatus.revoked
        row.revoked_at = datetime.now(timezone.utc)
        self.session.flush()
        return self._alias_model(row)

    def upsert_follow_up_reminder(
        self,
        reminder: FollowUpReminder,
    ) -> FollowUpReminder:
        row = (
            self.session.query(FollowUpReminderORM)
            .filter(
                FollowUpReminderORM.provider == reminder.provider,
                FollowUpReminderORM.email_id == reminder.email_id,
                FollowUpReminderORM.owner_email == reminder.owner_email,
                FollowUpReminderORM.status == FollowUpReminderStatus.active,
            )
            .order_by(FollowUpReminderORM.created_at.desc())
            .first()
        )
        payload = reminder.model_dump(mode="json")
        if row is None:
            row = FollowUpReminderORM(
                provider=payload["provider"],
                email_id=payload["email_id"],
                owner_email=payload["owner_email"],
                thread_id=payload["thread_id"],
                run_id=payload["run_id"],
                sender=payload["sender"],
                subject=payload["subject"],
                preview=payload["preview"],
                priority=payload["priority"],
                category=payload["category"],
                note=payload["note"],
                source=payload["source"],
                due_at=reminder.due_at,
                status=payload["status"],
                created_at=reminder.created_at,
                updated_at=reminder.updated_at,
                completed_at=reminder.completed_at,
            )
            self.session.add(row)
            self.session.flush()
            return self._reminder_model(row)

        row.thread_id = payload["thread_id"]
        row.run_id = payload["run_id"]
        row.sender = payload["sender"]
        row.subject = payload["subject"]
        row.preview = payload["preview"]
        row.priority = payload["priority"]
        row.category = payload["category"]
        row.note = payload["note"]
        row.source = payload["source"]
        row.due_at = reminder.due_at
        row.status = payload["status"]
        row.updated_at = reminder.updated_at
        row.completed_at = reminder.completed_at
        self.session.flush()
        return self._reminder_model(row)

    def list_follow_up_reminders(
        self,
        *,
        owner_email: Optional[str] = None,
        status: Optional[str] = None,
        due_before: Optional[datetime] = None,
        limit: int = 25,
    ) -> list[FollowUpReminder]:
        query = self.session.query(FollowUpReminderORM)
        if owner_email:
            query = query.filter(FollowUpReminderORM.owner_email == owner_email)
        if status:
            query = query.filter(FollowUpReminderORM.status == status)
        if due_before is not None:
            query = query.filter(FollowUpReminderORM.due_at <= due_before)
        rows = (
            query.order_by(
                FollowUpReminderORM.due_at.asc(),
                FollowUpReminderORM.updated_at.desc(),
            )
            .limit(limit)
            .all()
        )
        return [self._reminder_model(row) for row in rows]

    def update_follow_up_reminder_status(
        self,
        reminder_id: int,
        status: str,
    ) -> Optional[FollowUpReminder]:
        row = self.session.get(FollowUpReminderORM, reminder_id)
        if row is None:
            return None
        row.status = status
        row.updated_at = datetime.now(timezone.utc)
        if status == FollowUpReminderStatus.completed:
            row.completed_at = row.updated_at
        elif status == FollowUpReminderStatus.dismissed:
            row.completed_at = None
        self.session.flush()
        return self._reminder_model(row)

    def list_run_emails(self, run_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
        rows = (
            self.session.query(EmailRecordORM)
            .filter(EmailRecordORM.run_id == run_id)
            .order_by(EmailRecordORM.received_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "email_id": row.email_id,
                "thread_id": row.thread_id,
                "sender": row.sender,
                "subject": row.subject,
                "snippet": row.snippet,
                "body_preview": row.body_preview,
                "received_at": row.received_at.isoformat(),
                "labels": row.labels,
                "has_attachments": row.has_attachments,
                "unread": row.unread,
            }
            for row in rows
        ]

    def count_run_emails(self, run_id: str) -> int:
        return self.session.query(EmailRecordORM).filter(EmailRecordORM.run_id == run_id).count()

    def list_run_email_details(
        self,
        run_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        q: Optional[str] = None,
        unread_only: bool = False,
        time_range: Optional[str] = None,
    ) -> list[dict]:
        query = self._run_email_details_query(
            run_id,
            priority=priority,
            category=category,
            q=q,
            unread_only=unread_only,
            time_range=time_range,
        )
        rows = (
            query.order_by(EmailRecordORM.received_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "email_id": email.email_id,
                "thread_id": email.thread_id,
                "sender": email.sender,
                "subject": email.subject,
                "snippet": email.snippet,
                "body_preview": email.body_preview,
                "received_at": email.received_at.isoformat(),
                "labels": email.labels,
                "has_attachments": email.has_attachments,
                "unread": email.unread,
                "classification": {
                    "category": classification.category,
                    "priority": classification.priority,
                    "confidence": classification.confidence,
                    "reason": classification.reason,
                },
            }
            for email, classification in rows
        ]

    def get_run_email_detail(self, run_id: str, email_id: str) -> Optional[dict]:
        row = (
            self.session.query(EmailRecordORM, ClassificationORM)
            .join(
                ClassificationORM,
                and_(
                    ClassificationORM.run_id == EmailRecordORM.run_id,
                    ClassificationORM.email_id == EmailRecordORM.email_id,
                ),
            )
            .filter(
                EmailRecordORM.run_id == run_id,
                EmailRecordORM.email_id == email_id,
            )
            .first()
        )
        if row is None:
            return None
        email, classification = row
        return {
            "email_id": email.email_id,
            "thread_id": email.thread_id,
            "sender": email.sender,
            "subject": email.subject,
            "snippet": email.snippet,
            "body_preview": email.body_preview,
            "received_at": email.received_at.isoformat(),
            "labels": email.labels,
            "has_attachments": email.has_attachments,
            "unread": email.unread,
            "classification": {
                "category": classification.category,
                "priority": classification.priority,
                "confidence": classification.confidence,
                "reason": classification.reason,
            },
        }

    def count_run_email_details(
        self,
        run_id: str,
        *,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        q: Optional[str] = None,
        unread_only: bool = False,
        time_range: Optional[str] = None,
    ) -> int:
        return self._run_email_details_query(
            run_id,
            priority=priority,
            category=category,
            q=q,
            unread_only=unread_only,
            time_range=time_range,
        ).count()

    def count_run_high_priority_emails(self, run_id: str) -> int:
        return self._run_email_details_query(run_id).filter(
            ClassificationORM.priority.in_(["critical", "high"])
        ).count()

    def count_run_attachment_emails(self, run_id: str) -> int:
        return self._run_email_details_query(run_id).filter(
            EmailRecordORM.has_attachments.is_(True)
        ).count()

    def count_run_auto_label_candidates(self, run_id: str) -> int:
        return self._run_email_details_query(run_id).filter(
            or_(
                ClassificationORM.category != "unknown",
                ClassificationORM.priority.in_(["critical", "high"]),
                EmailRecordORM.has_attachments.is_(True),
            )
        ).count()

    def count_run_recommendations_by_status(self, run_id: str, status: str) -> int:
        return (
            self.session.query(RecommendationORM)
            .filter(
                RecommendationORM.run_id == run_id,
                RecommendationORM.status == status,
            )
            .count()
        )

    def list_run_recommendations(
        self,
        run_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> list[dict]:
        query = self.session.query(RecommendationORM).filter(RecommendationORM.run_id == run_id)
        if status:
            query = query.filter(RecommendationORM.status == status)
        rows = query.order_by(RecommendationORM.confidence.desc()).offset(offset).limit(limit).all()
        return [
            {
                "email_id": row.email_id,
                "recommended_action": row.recommended_action,
                "reason": row.reason,
                "confidence": row.confidence,
                "status": row.status,
                "requires_approval": row.requires_approval,
                "blocked_reason": row.blocked_reason,
                "proposed_labels": row.proposed_labels,
            }
            for row in rows
        ]

    def count_run_recommendations(self, run_id: str, *, status: Optional[str] = None) -> int:
        query = self.session.query(RecommendationORM).filter(RecommendationORM.run_id == run_id)
        if status:
            query = query.filter(RecommendationORM.status == status)
        return query.count()

    def list_run_recommendation_details(
        self,
        run_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> list[dict]:
        query = (
            self.session.query(RecommendationORM, EmailRecordORM, ClassificationORM)
            .join(
                EmailRecordORM,
                and_(
                    EmailRecordORM.run_id == RecommendationORM.run_id,
                    EmailRecordORM.email_id == RecommendationORM.email_id,
                ),
            )
            .join(
                ClassificationORM,
                and_(
                    ClassificationORM.run_id == RecommendationORM.run_id,
                    ClassificationORM.email_id == RecommendationORM.email_id,
                ),
            )
            .filter(RecommendationORM.run_id == run_id)
        )
        if status:
            query = query.filter(RecommendationORM.status == status)

        rows = (
            query.order_by(RecommendationORM.confidence.desc(), EmailRecordORM.received_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "email_id": recommendation.email_id,
                "recommended_action": recommendation.recommended_action,
                "reason": recommendation.reason,
                "confidence": recommendation.confidence,
                "status": recommendation.status,
                "requires_approval": recommendation.requires_approval,
                "blocked_reason": recommendation.blocked_reason,
                "proposed_labels": recommendation.proposed_labels,
                "email": {
                    "sender": email.sender,
                    "subject": email.subject,
                    "received_at": email.received_at.isoformat(),
                    "has_attachments": email.has_attachments,
                    "snippet": email.snippet,
                },
                "classification": {
                    "category": classification.category,
                    "priority": classification.priority,
                    "confidence": classification.confidence,
                    "reason": classification.reason,
                },
            }
            for recommendation, email, classification in rows
        ]

    def get_run_recommendation_detail(self, run_id: str, email_id: str) -> Optional[dict]:
        row = (
            self.session.query(RecommendationORM, EmailRecordORM, ClassificationORM)
            .join(
                EmailRecordORM,
                and_(
                    EmailRecordORM.run_id == RecommendationORM.run_id,
                    EmailRecordORM.email_id == RecommendationORM.email_id,
                ),
            )
            .join(
                ClassificationORM,
                and_(
                    ClassificationORM.run_id == RecommendationORM.run_id,
                    ClassificationORM.email_id == RecommendationORM.email_id,
                ),
            )
            .filter(
                RecommendationORM.run_id == run_id,
                RecommendationORM.email_id == email_id,
            )
            .order_by(RecommendationORM.confidence.desc())
            .first()
        )
        if row is None:
            return None
        recommendation, email, classification = row
        return {
            "email_id": recommendation.email_id,
            "recommended_action": recommendation.recommended_action,
            "reason": recommendation.reason,
            "confidence": recommendation.confidence,
            "status": recommendation.status,
            "requires_approval": recommendation.requires_approval,
            "blocked_reason": recommendation.blocked_reason,
            "proposed_labels": recommendation.proposed_labels,
            "email": {
                "sender": email.sender,
                "subject": email.subject,
                "received_at": email.received_at.isoformat(),
                "has_attachments": email.has_attachments,
                "snippet": email.snippet,
                "body_preview": email.body_preview,
                "labels": email.labels,
                "thread_id": email.thread_id,
                "unread": email.unread,
            },
            "classification": {
                "category": classification.category,
                "priority": classification.priority,
                "confidence": classification.confidence,
                "reason": classification.reason,
            },
        }

    def list_action_items_for_email(self, run_id: str, email_id: str) -> list[dict]:
        rows = (
            self.session.query(ActionItemORM)
            .filter(ActionItemORM.run_id == run_id, ActionItemORM.email_id == email_id)
            .order_by(ActionItemORM.id.asc())
            .all()
        )
        return [
            {
                "email_id": row.email_id,
                "action_type": row.action_type,
                "description": row.description,
                "due_hint": row.due_hint,
                "requires_reply": row.requires_reply,
            }
            for row in rows
        ]

    def build_execution_result(self, run_id: str, email_ids: list[str]) -> TriageRunResult:
        from inboxanchor.models import (
            EmailActionItem,
            EmailClassification,
            EmailMessage,
            EmailRecommendation,
            InboxDigest,
            TriageRunResult,
        )

        run = self.session.get(TriageRunORM, run_id)
        if run is None:
            raise KeyError(run_id)

        email_rows = (
            self.session.query(EmailRecordORM)
            .filter(EmailRecordORM.run_id == run_id, EmailRecordORM.email_id.in_(email_ids))
            .all()
        )
        class_rows = (
            self.session.query(ClassificationORM)
            .filter(ClassificationORM.run_id == run_id, ClassificationORM.email_id.in_(email_ids))
            .all()
        )
        action_rows = (
            self.session.query(ActionItemORM)
            .filter(ActionItemORM.run_id == run_id, ActionItemORM.email_id.in_(email_ids))
            .all()
        )
        recommendation_rows = (
            self.session.query(RecommendationORM)
            .filter(RecommendationORM.run_id == run_id, RecommendationORM.email_id.in_(email_ids))
            .all()
        )

        payload = run.raw_payload
        email_models = [
            EmailMessage(
                id=row.email_id,
                thread_id=row.thread_id,
                sender=row.sender,
                subject=row.subject,
                snippet=row.snippet,
                body_preview=row.body_preview,
                body_full=(self.get_mailbox_email(run.provider, row.email_id) or {}).get(
                    "body_full",
                    row.body_preview,
                ),
                received_at=row.received_at,
                labels=row.labels,
                has_attachments=row.has_attachments,
                unread=row.unread,
            )
            for row in email_rows
        ]
        classifications = {
            row.email_id: EmailClassification(
                category=row.category,
                priority=row.priority,
                confidence=row.confidence,
                reason=row.reason,
            )
            for row in class_rows
        }
        action_items = {}
        for row in action_rows:
            action_items.setdefault(row.email_id, []).append(
                EmailActionItem(
                    email_id=row.email_id,
                    action_type=row.action_type,
                    description=row.description,
                    due_hint=row.due_hint,
                    requires_reply=row.requires_reply,
                )
            )
        recommendations = [
            EmailRecommendation(
                email_id=row.email_id,
                recommended_action=row.recommended_action,
                reason=row.reason,
                confidence=row.confidence,
                status=row.status,
                requires_approval=row.requires_approval,
                blocked_reason=row.blocked_reason,
                proposed_labels=row.proposed_labels,
            )
            for row in recommendation_rows
        ]
        digest = InboxDigest.model_validate(payload["digest"])
        return TriageRunResult(
            run_id=run_id,
            provider=run.provider,
            dry_run=run.dry_run,
            total_emails=run.total_emails,
            scanned_emails=payload["scanned_emails"],
            batch_size=payload["batch_size"],
            batch_count=payload["batch_count"],
            email_preview_limit=payload["email_preview_limit"],
            recommendation_preview_limit=payload["recommendation_preview_limit"],
            email_preview_truncated=payload.get("email_preview_truncated", False),
            recommendation_preview_truncated=payload.get(
                "recommendation_preview_truncated",
                False,
            ),
            emails=email_models,
            classifications=classifications,
            action_items=action_items,
            recommendations=recommendations,
            digest=digest,
            reply_drafts={},
            approvals_required=payload["approvals_required"],
            blocked_actions=payload["blocked_actions"],
        )

    def add_audit_entry(self, entry: AuditLogEntry) -> None:
        self.session.add(
            AuditLogORM(
                email_id=entry.email_id,
                proposed_action=entry.proposed_action,
                final_action=entry.final_action,
                approved_by_user=entry.approved_by_user,
                timestamp=entry.timestamp,
                reason=entry.reason,
                confidence=entry.confidence,
                agent_decision=entry.agent_decision,
                safety_verifier_status=entry.safety_verifier_status,
            )
        )

    def list_audit_entries(self) -> list[AuditLogEntry]:
        rows = self.session.query(AuditLogORM).order_by(AuditLogORM.timestamp.desc()).all()
        return [
            AuditLogEntry(
                email_id=row.email_id,
                proposed_action=row.proposed_action,
                final_action=row.final_action,
                approved_by_user=row.approved_by_user,
                timestamp=row.timestamp,
                reason=row.reason,
                confidence=row.confidence,
                agent_decision=row.agent_decision,
                safety_verifier_status=row.safety_verifier_status,
            )
            for row in rows
        ]
