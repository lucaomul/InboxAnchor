from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import uuid4

from inboxanchor.agents import (
    ActionExtractorAgent,
    ClassifierAgent,
    PriorityAgent,
    ReplyDrafterAgent,
    SafetyVerifierAgent,
    SummarizerAgent,
)
from inboxanchor.connectors.base import EmailProvider, ProviderActionResult
from inboxanchor.core.rules import RulesEngine
from inboxanchor.infra.audit_log import AuditLogger
from inboxanchor.infra.database import session_scope
from inboxanchor.infra.repository import InboxRepository
from inboxanchor.models import (
    AutomationDecision,
    EmailClassification,
    EmailMessage,
    EmailRecommendation,
    TriageRunResult,
    WorkspacePolicy,
)
from inboxanchor.models.email import RecommendationStatus, SafetyStatus


class TriageEngine:
    def __init__(
        self,
        provider: EmailProvider,
        *,
        classifier: Optional[ClassifierAgent] = None,
        priority_agent: Optional[PriorityAgent] = None,
        summarizer: Optional[SummarizerAgent] = None,
        action_extractor: Optional[ActionExtractorAgent] = None,
        reply_drafter: Optional[ReplyDrafterAgent] = None,
        safety_verifier: Optional[SafetyVerifierAgent] = None,
        rules_engine: Optional[RulesEngine] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        self.provider = provider
        self.classifier = classifier or ClassifierAgent()
        self.priority_agent = priority_agent or PriorityAgent()
        self.summarizer = summarizer or SummarizerAgent()
        self.action_extractor = action_extractor or ActionExtractorAgent()
        self.reply_drafter = reply_drafter or ReplyDrafterAgent()
        self.safety_verifier = safety_verifier or SafetyVerifierAgent()
        self.rules_engine = rules_engine or RulesEngine()
        self.audit_logger = audit_logger or AuditLogger()

    def run(
        self,
        *,
        dry_run: bool = True,
        limit: int = 50,
        batch_size: int = 100,
        category_filters: Optional[list[str]] = None,
        confidence_threshold: float = 0.65,
        email_preview_limit: int = 100,
        recommendation_preview_limit: int = 150,
        workspace_policy: Optional[WorkspacePolicy] = None,
        progress_callback: Optional[Callable[[dict], None]] = None,
        time_range: Optional[str] = None,
    ) -> TriageRunResult:
        workspace_policy = workspace_policy or WorkspacePolicy()
        classifications: dict[str, EmailClassification] = {}
        action_items = defaultdict(list)
        reply_drafts: dict[str, str] = {}
        recommendations: list[EmailRecommendation] = []
        all_emails: list[EmailMessage] = []
        batch_count = 0
        scanned_emails = 0
        total_action_items = 0

        if progress_callback:
            progress_callback(
                {
                    "stage": "starting",
                    "provider": self.provider.provider_name,
                    "limit": limit,
                    "batch_size": batch_size,
                    "scanned_emails": 0,
                    "processed_emails": 0,
                    "read_count": 0,
                    "action_item_count": 0,
                    "recommendation_count": 0,
                    "batch_count": 0,
                }
            )

        for batch in self.provider.iter_unread_batches(
            limit=limit,
            batch_size=batch_size,
            include_body=True,
            time_range=time_range,
        ):
            batch_count += 1
            if progress_callback:
                progress_callback(
                    {
                        "stage": "reading_batch",
                        "provider": self.provider.provider_name,
                        "limit": limit,
                        "batch_size": batch_size,
                        "scanned_emails": scanned_emails,
                        "processed_emails": len(all_emails),
                        "read_count": len(all_emails),
                        "action_item_count": total_action_items,
                        "recommendation_count": len(recommendations),
                        "batch_count": batch_count,
                    }
                )
            for email in batch:
                scanned_emails += 1
                classification = self.priority_agent.prioritize(
                    email,
                    self.classifier.classify(email),
                )
                if category_filters and classification.category not in category_filters:
                    continue
                if classification.confidence < confidence_threshold and not email.has_attachments:
                    classification = classification.model_copy(
                        update={
                            "reason": (
                                f"{classification.reason} "
                                "Confidence below target threshold."
                            )
                        }
                    )

                items = self.action_extractor.extract(
                    email,
                    classification=classification,
                )
                recommendation = self.safety_verifier.verify(
                    email,
                    classification,
                    self.rules_engine.recommend(
                        email,
                        classification,
                        now=datetime.now(timezone.utc),
                        policy=workspace_policy,
                    ),
                    policy=workspace_policy,
                )

                classifications[email.id] = classification
                action_items[email.id].extend(items)
                total_action_items += len(items)
                if items:
                    draft = self.reply_drafter.draft(
                        email,
                        items,
                        classification=classification,
                    )
                    if draft:
                        reply_drafts[email.id] = draft
                recommendations.append(recommendation)
                all_emails.append(email)
                if progress_callback and (scanned_emails <= 5 or scanned_emails % 10 == 0):
                    progress_callback(
                        {
                            "stage": "triaging",
                            "provider": self.provider.provider_name,
                            "limit": limit,
                            "batch_size": batch_size,
                            "scanned_emails": scanned_emails,
                            "processed_emails": len(all_emails),
                            "read_count": len(all_emails),
                            "action_item_count": total_action_items,
                            "recommendation_count": len(recommendations),
                            "batch_count": batch_count,
                            "latest_subject": email.subject,
                        }
                    )

        digest = self.summarizer.build_digest(all_emails, classifications)
        approvals_required = [
            rec.email_id
            for rec in recommendations
            if rec.status == RecommendationStatus.requires_approval
        ]
        blocked_actions = [
            rec.email_id
            for rec in recommendations
            if rec.status == RecommendationStatus.blocked
        ]
        preview_recommendations = self._select_recommendation_preview(
            recommendations,
            classifications,
            limit=recommendation_preview_limit,
        )
        preview_emails = self._select_email_preview(
            all_emails,
            classifications,
            limit=email_preview_limit,
            required_email_ids={item.email_id for item in preview_recommendations},
        )
        preview_email_ids = {email.id for email in preview_emails}
        preview_action_items = {
            email_id: items
            for email_id, items in action_items.items()
            if email_id in preview_email_ids
        }
        preview_reply_drafts = {
            email_id: draft
            for email_id, draft in reply_drafts.items()
            if email_id in preview_email_ids
        }
        preview_classifications = {
            email_id: classification
            for email_id, classification in classifications.items()
            if email_id in preview_email_ids
        }

        result = TriageRunResult(
            run_id=f"triage_{uuid4().hex[:12]}",
            provider=self.provider.provider_name,
            dry_run=dry_run,
            total_emails=len(all_emails),
            scanned_emails=scanned_emails,
            batch_size=batch_size,
            batch_count=batch_count,
            email_preview_limit=email_preview_limit,
            recommendation_preview_limit=recommendation_preview_limit,
            email_preview_truncated=len(all_emails) > len(preview_emails),
            recommendation_preview_truncated=len(recommendations) > len(preview_recommendations),
            emails=preview_emails,
            classifications=preview_classifications,
            action_items=preview_action_items,
            recommendations=preview_recommendations,
            digest=digest,
            reply_drafts=preview_reply_drafts,
            approvals_required=approvals_required,
            blocked_actions=blocked_actions,
        )
        with session_scope() as session:
            InboxRepository(session).save_run(
                result,
                persisted_emails=all_emails,
                persisted_classifications=classifications,
                persisted_action_items=dict(action_items),
                persisted_recommendations=recommendations,
            )
        if progress_callback:
            progress_callback(
                {
                    "stage": "complete",
                    "provider": self.provider.provider_name,
                    "limit": limit,
                    "batch_size": batch_size,
                    "scanned_emails": scanned_emails,
                    "processed_emails": len(all_emails),
                    "read_count": len(all_emails),
                    "action_item_count": total_action_items,
                    "recommendation_count": len(recommendations),
                    "batch_count": batch_count,
                    "run_id": result.run_id,
                }
            )
        return result

    def _recommendation_rank(
        self,
        recommendation: EmailRecommendation,
        classification: EmailClassification,
    ) -> tuple[int, int, float]:
        status_value = getattr(recommendation.status, "value", recommendation.status)
        priority_value = getattr(classification.priority, "value", classification.priority)
        status_rank = {
            RecommendationStatus.blocked: 0,
            RecommendationStatus.requires_approval: 1,
            RecommendationStatus.safe: 2,
        }[status_value]
        priority_rank = {
            "critical": 0,
            "high": 1,
            "medium": 2,
            "low": 3,
        }[priority_value]
        return (status_rank, priority_rank, -recommendation.confidence)

    def _select_recommendation_preview(
        self,
        recommendations: list[EmailRecommendation],
        classifications: dict[str, EmailClassification],
        *,
        limit: int,
    ) -> list[EmailRecommendation]:
        ranked = sorted(
            recommendations,
            key=lambda rec: self._recommendation_rank(rec, classifications[rec.email_id]),
        )
        return ranked[:limit]

    def _select_email_preview(
        self,
        emails: list[EmailMessage],
        classifications: dict[str, EmailClassification],
        *,
        limit: int,
        required_email_ids: Optional[set[str]] = None,
    ) -> list[EmailMessage]:
        ranked = sorted(
            emails,
            key=lambda email: (
                {
                    "critical": 0,
                    "high": 1,
                    "medium": 2,
                    "low": 3,
                }[
                    getattr(
                        classifications[email.id].priority,
                        "value",
                        classifications[email.id].priority,
                    )
                ],
                email.received_at.timestamp() * -1,
            ),
        )
        required_email_ids = required_email_ids or set()
        capped_limit = max(limit, len(required_email_ids))
        preview: list[EmailMessage] = []
        seen: set[str] = set()

        for email in ranked:
            if email.id not in required_email_ids:
                continue
            preview.append(email)
            seen.add(email.id)

        for email in ranked:
            if email.id in seen:
                continue
            if len(preview) >= capped_limit:
                break
            preview.append(email)
            seen.add(email.id)

        return preview

    def execute_actions(
        self,
        run_result: TriageRunResult,
        *,
        approved_email_ids: list[str],
        explicit_trash_confirmation: bool = False,
    ) -> list[AutomationDecision]:
        decisions: list[AutomationDecision] = []
        grouped: dict[str, list[str]] = defaultdict(list)

        for recommendation in run_result.recommendations:
            if recommendation.email_id not in approved_email_ids:
                continue
            if recommendation.status == RecommendationStatus.blocked:
                continue
            grouped[recommendation.recommended_action].append(recommendation.email_id)
            decisions.append(
                AutomationDecision(
                    email_id=recommendation.email_id,
                    proposed_action=recommendation.recommended_action,
                    final_action=recommendation.recommended_action,
                    approved_by_user=True,
                    reason=recommendation.reason,
                    confidence=recommendation.confidence,
                    safety_verifier_status=(
                        SafetyStatus.allowed
                        if recommendation.status == RecommendationStatus.safe
                        else SafetyStatus.requires_review
                    ),
                )
            )
            if recommendation.proposed_labels:
                self.provider.apply_labels(
                    [recommendation.email_id],
                    recommendation.proposed_labels,
                    dry_run=run_result.dry_run,
                )

        results: list[ProviderActionResult] = []
        if grouped.get("mark_read"):
            results.append(
                self.provider.batch_mark_as_read(
                    grouped["mark_read"],
                    dry_run=run_result.dry_run,
                )
            )
        if grouped.get("archive"):
            results.append(
                self.provider.archive_emails(
                    grouped["archive"],
                    dry_run=run_result.dry_run,
                )
            )
        if grouped.get("trash"):
            results.append(
                self.provider.move_to_trash(
                    grouped["trash"],
                    explicit_confirmation=explicit_trash_confirmation,
                    dry_run=run_result.dry_run,
                )
            )

        results_map = {email_id: result for result in results for email_id in result.email_ids}
        finalized_decisions: list[AutomationDecision] = []
        with session_scope() as session:
            repository = InboxRepository(session)
            for decision in decisions:
                provider_result = results_map.get(decision.email_id)
                final_action = decision.final_action or decision.proposed_action
                safety_status = decision.safety_verifier_status
                if provider_result and not provider_result.executed and not run_result.dry_run:
                    final_action = "blocked"
                    safety_status = SafetyStatus.blocked
                finalized = decision.model_copy(
                    update={
                        "final_action": final_action,
                        "safety_verifier_status": safety_status,
                    }
                )
                audit_entry = self.audit_logger.create_entry(finalized)
                repository.add_audit_entry(audit_entry)
                finalized_decisions.append(finalized)
        return finalized_decisions
