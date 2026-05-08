from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_

from inboxanchor.infra.database import (
    ActionItemORM,
    AuditLogORM,
    ClassificationORM,
    EmailRecordORM,
    FollowUpReminderORM,
    ProviderCheckpointORM,
    ProviderConnectionORM,
    RecommendationORM,
    TriageRunORM,
    WorkspaceSettingsORM,
)
from inboxanchor.models import (
    AuditLogEntry,
    FollowUpReminder,
    FollowUpReminderStatus,
    ProviderConnectionState,
    TriageRunResult,
    WorkspaceSettings,
)


class InboxRepository:
    def __init__(self, session):
        self.session = session

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

    def get_run(self, run_id: str) -> Optional[dict]:
        run = self.session.get(TriageRunORM, run_id)
        return run.raw_payload if run else None

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
    ) -> list[dict]:
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

    def count_run_email_details(
        self,
        run_id: str,
        *,
        priority: Optional[str] = None,
        category: Optional[str] = None,
    ) -> int:
        query = (
            self.session.query(EmailRecordORM)
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
        return query.count()

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
