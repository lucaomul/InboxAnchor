from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Iterable, Optional

import streamlit as st

import inboxanchor.bootstrap as bootstrap_module
import inboxanchor.infra.repository as repository_module
from inboxanchor.app.ui import (
    card_close,
    card_open,
    inject_styles,
    render_callout,
    render_empty_state,
    render_metric_bar,
    render_operator_stage,
    render_pill_row,
)
from inboxanchor.infra.auth import AuthError, AuthService
from inboxanchor.infra.database import AuditLogORM, TriageRunORM, session_scope
from inboxanchor.models import AccountUser, TriageRunResult
from inboxanchor.models.email import EmailRecommendation, RecommendationStatus

CONNECTION_STATUS_OPTIONS = [
    "not_connected",
    "sandbox_ready",
    "configured",
    "connected",
    "needs_attention",
]

WORKSPACE_PLAYBOOKS = {
    "balanced": {
        "label": "Balanced Triage",
        "summary": "Conservative daily workflow with strong review gates and moderate scan depth.",
        "pills": ["safe default", "daily triage", "audit-first"],
        "settings": {
            "preferred_provider": "fake",
            "dry_run_default": True,
            "default_scan_limit": 500,
            "default_batch_size": 250,
            "default_confidence_threshold": 0.65,
            "default_email_preview_limit": 120,
            "default_recommendation_preview_limit": 180,
            "follow_up_radar_enabled": True,
            "follow_up_after_hours": 24,
            "follow_up_priority_floor": "medium",
            "operator_mode": "safe",
        },
        "policy": {},
    },
    "inbox_zero": {
        "label": "Inbox Zero Sweep",
        "summary": (
            "Aggressive cleanup for newsletters, promos, and low-priority backlog "
            "without removing human approval."
        ),
        "pills": ["cleanup", "bulk triage", "noise reduction"],
        "settings": {
            "preferred_provider": "fake",
            "dry_run_default": True,
            "default_scan_limit": 2000,
            "default_batch_size": 500,
            "default_confidence_threshold": 0.6,
            "default_email_preview_limit": 100,
            "default_recommendation_preview_limit": 260,
            "follow_up_radar_enabled": True,
            "follow_up_after_hours": 48,
            "follow_up_priority_floor": "high",
            "operator_mode": "balanced",
        },
        "policy": {
            "allow_newsletter_mark_read": True,
            "newsletter_confidence_threshold": 0.85,
            "allow_promo_archive": True,
            "promo_archive_age_days": 10,
            "allow_low_priority_cleanup": True,
            "low_priority_age_days": 5,
            "allow_spam_trash_recommendations": True,
        },
    },
    "founder_radar": {
        "label": "Founder Radar",
        "summary": (
            "Protect sensitive, finance, and high-priority threads while keeping "
            "the scan shallow and decisive."
        ),
        "pills": ["sensitive first", "exec view", "high confidence"],
        "settings": {
            "preferred_provider": "fake",
            "dry_run_default": True,
            "default_scan_limit": 350,
            "default_batch_size": 250,
            "default_confidence_threshold": 0.75,
            "default_email_preview_limit": 140,
            "default_recommendation_preview_limit": 160,
            "follow_up_radar_enabled": True,
            "follow_up_after_hours": 18,
            "follow_up_priority_floor": "medium",
            "operator_mode": "safe",
        },
        "policy": {
            "allow_low_priority_cleanup": False,
            "require_review_for_finance": True,
            "require_review_for_personal": True,
            "require_review_for_attachments": True,
        },
    },
    "sales_follow_up": {
        "label": "Sales Follow-Up",
        "summary": (
            "Prioritize replies, opportunities, and follow-up-ready drafts before "
            "broad cleanup work."
        ),
        "pills": ["reply queue", "opportunities", "follow-up"],
        "settings": {
            "preferred_provider": "fake",
            "dry_run_default": True,
            "default_scan_limit": 750,
            "default_batch_size": 500,
            "default_confidence_threshold": 0.6,
            "default_email_preview_limit": 160,
            "default_recommendation_preview_limit": 220,
            "follow_up_radar_enabled": True,
            "follow_up_after_hours": 12,
            "follow_up_priority_floor": "medium",
            "operator_mode": "balanced",
        },
        "policy": {
            "allow_promo_archive": False,
            "allow_low_priority_cleanup": False,
            "require_review_for_finance": True,
            "require_review_for_personal": True,
        },
    },
}


def _fallback_provider_profile(provider_name: Optional[str]):
    profiles = {
        "fake": SimpleNamespace(
            slug="fake",
            label="Demo Workspace",
            family="demo",
            auth_mode="none",
            status="ready",
            live_ready=True,
            best_for="Guided product demos, UX checks, and deterministic testing.",
            capabilities=[
                "Seeded unread inbox",
                "Predictable action recommendations",
                "Fast 10K-scale simulation",
            ],
            safety_notes=[
                "No real mailbox access.",
                "Best choice for visual testing and regression coverage.",
            ],
        ),
        "gmail": SimpleNamespace(
            slug="gmail",
            label="Gmail",
            family="gmail-api",
            auth_mode="oauth",
            status="oauth-ready",
            live_ready=False,
            best_for="Best future fit for production-grade personal and workspace inboxes.",
            capabilities=["Batch triage", "Labels", "Archive/trash policy support"],
            safety_notes=[
                "Needs a live Gmail API transport.",
                "Full OAuth callback handling is still a dedicated next pass.",
            ],
        ),
        "imap": SimpleNamespace(
            slug="imap",
            label="Generic IMAP",
            family="imap",
            auth_mode="password-or-app-password",
            status="extensible",
            live_ready=False,
            best_for="Generic IMAP-family development and custom mailbox experiments.",
            capabilities=["Unified inbox abstraction", "Archive/read/trash surface"],
            safety_notes=["Provider-specific auth still needs live transport wiring."],
        ),
        "yahoo": SimpleNamespace(
            slug="yahoo",
            label="Yahoo Mail",
            family="imap",
            auth_mode="app-password",
            status="planned-live",
            live_ready=False,
            best_for="Yahoo support via the shared IMAP-family connector path.",
            capabilities=["Triage architecture", "Safe cleanup path"],
            safety_notes=["Needs provider-specific transport and onboarding polish."],
        ),
        "outlook": SimpleNamespace(
            slug="outlook",
            label="Outlook / Microsoft",
            family="imap",
            auth_mode="app-password-or-oauth-later",
            status="planned-live",
            live_ready=False,
            best_for="Microsoft inboxes until a dedicated richer connector lands.",
            capabilities=["Large-inbox triage", "Approval and audit workflow"],
            safety_notes=["Graph-native transport will be better than generic IMAP long term."],
        ),
    }
    slug = (provider_name or "fake").lower()
    return profiles.get(slug, profiles["fake"])


def _provider_options() -> list[str]:
    options = getattr(
        bootstrap_module,
        "PROVIDER_OPTIONS",
        ["fake", "gmail", "imap", "yahoo", "outlook"],
    )
    return list(options)


def _provider_profile(provider_name: Optional[str]):
    resolver = getattr(bootstrap_module, "get_provider_profile", None)
    if callable(resolver):
        try:
            return resolver(provider_name)
        except Exception:
            pass
    return _fallback_provider_profile(provider_name)


def _playbook_choices() -> list[str]:
    return list(WORKSPACE_PLAYBOOKS)


def _playbook_definition(slug: str) -> dict[str, Any]:
    return WORKSPACE_PLAYBOOKS.get(slug, WORKSPACE_PLAYBOOKS["balanced"])


def _service_class():
    service_cls = getattr(bootstrap_module, "InboxAnchorService", None)
    if service_cls is None:
        raise RuntimeError("InboxAnchorService is unavailable in the current bootstrap module.")
    return service_cls


def _repository_class():
    repository_cls = getattr(repository_module, "InboxRepository", None)
    if repository_cls is None:
        raise RuntimeError("InboxRepository is unavailable in the current repository module.")
    return repository_cls


def _service() -> Any:
    if "service" not in st.session_state:
        st.session_state.service = _service_class()()
    return st.session_state.service


def _workspace_settings(service: Any):
    try:
        return service.load_workspace_settings()
    except Exception:
        return SimpleNamespace(
            preferred_provider="fake",
            dry_run_default=True,
            default_scan_limit=500,
            default_batch_size=250,
            default_confidence_threshold=0.65,
            default_email_preview_limit=120,
            default_recommendation_preview_limit=180,
            follow_up_radar_enabled=True,
            follow_up_after_hours=24,
            follow_up_priority_floor="medium",
            onboarding_completed=False,
            operator_mode="safe",
            policy=SimpleNamespace(
                allow_newsletter_mark_read=True,
                newsletter_confidence_threshold=0.9,
                allow_promo_archive=True,
                promo_archive_age_days=14,
                allow_low_priority_cleanup=True,
                low_priority_age_days=7,
                allow_spam_trash_recommendations=True,
                auto_label_recommendations=True,
                require_review_for_attachments=True,
                require_review_for_finance=True,
                require_review_for_personal=True,
            ),
        )


def _provider_connection_state(service: Any, provider_name: str):
    try:
        return service.load_provider_connection(provider_name)
    except Exception:
        return SimpleNamespace(
            provider=provider_name,
            status="not_connected",
            account_hint="",
            sync_enabled=False,
            dry_run_only=True,
            last_tested_at=None,
            notes="",
        )


def _copy_settings(settings: Any, update: dict[str, Any]):
    existing_policy = settings.policy if hasattr(settings, "policy") else None
    if hasattr(settings, "model_copy"):
        return settings.model_copy(update=update)
    payload = {
        "preferred_provider": getattr(settings, "preferred_provider", "fake"),
        "dry_run_default": getattr(settings, "dry_run_default", True),
        "default_scan_limit": getattr(settings, "default_scan_limit", 500),
        "default_batch_size": getattr(settings, "default_batch_size", 250),
        "default_confidence_threshold": getattr(settings, "default_confidence_threshold", 0.65),
        "default_email_preview_limit": getattr(settings, "default_email_preview_limit", 120),
        "default_recommendation_preview_limit": getattr(
            settings, "default_recommendation_preview_limit", 180
        ),
        "follow_up_radar_enabled": getattr(settings, "follow_up_radar_enabled", True),
        "follow_up_after_hours": getattr(settings, "follow_up_after_hours", 24),
        "follow_up_priority_floor": getattr(settings, "follow_up_priority_floor", "medium"),
        "onboarding_completed": getattr(settings, "onboarding_completed", False),
        "operator_mode": getattr(settings, "operator_mode", "safe"),
        "policy": update.get("policy", existing_policy),
        "updated_at": getattr(settings, "updated_at", datetime.now(timezone.utc)),
    }
    payload.update(update)
    workspace_settings_cls = getattr(bootstrap_module, "WorkspaceSettings", None)
    if workspace_settings_cls is None:
        from inboxanchor.models import WorkspaceSettings

        workspace_settings_cls = WorkspaceSettings
    return workspace_settings_cls.model_validate(payload)


def _copy_policy(policy: Any, update: dict[str, Any]):
    if hasattr(policy, "model_copy"):
        return policy.model_copy(update=update)
    payload = {
        "allow_newsletter_mark_read": getattr(policy, "allow_newsletter_mark_read", True),
        "newsletter_confidence_threshold": getattr(policy, "newsletter_confidence_threshold", 0.9),
        "allow_promo_archive": getattr(policy, "allow_promo_archive", True),
        "promo_archive_age_days": getattr(policy, "promo_archive_age_days", 14),
        "allow_low_priority_cleanup": getattr(policy, "allow_low_priority_cleanup", True),
        "low_priority_age_days": getattr(policy, "low_priority_age_days", 7),
        "allow_spam_trash_recommendations": getattr(
            policy, "allow_spam_trash_recommendations", True
        ),
        "auto_label_recommendations": getattr(policy, "auto_label_recommendations", True),
        "require_review_for_attachments": getattr(
            policy, "require_review_for_attachments", True
        ),
        "require_review_for_finance": getattr(policy, "require_review_for_finance", True),
        "require_review_for_personal": getattr(policy, "require_review_for_personal", True),
    }
    payload.update(update)
    workspace_policy_cls = getattr(bootstrap_module, "WorkspacePolicy", None)
    if workspace_policy_cls is None:
        from inboxanchor.models import WorkspacePolicy

        workspace_policy_cls = WorkspacePolicy
    return workspace_policy_cls.model_validate(payload)


def _copy_provider_connection(connection: Any, update: dict[str, Any]):
    if hasattr(connection, "model_copy"):
        return connection.model_copy(update=update)
    payload = {
        "provider": getattr(connection, "provider", "fake"),
        "status": getattr(connection, "status", "not_connected"),
        "account_hint": getattr(connection, "account_hint", ""),
        "sync_enabled": getattr(connection, "sync_enabled", False),
        "dry_run_only": getattr(connection, "dry_run_only", True),
        "last_tested_at": getattr(connection, "last_tested_at", None),
        "notes": getattr(connection, "notes", ""),
    }
    payload.update(update)
    provider_connection_cls = getattr(bootstrap_module, "ProviderConnectionState", None)
    if provider_connection_cls is None:
        from inboxanchor.models import ProviderConnectionState

        provider_connection_cls = ProviderConnectionState
    return provider_connection_cls.model_validate(payload)


def _sync_workspace_control_state(settings: Any) -> None:
    st.session_state.workspace_provider = getattr(settings, "preferred_provider", "fake")
    st.session_state.workspace_dry_run = getattr(settings, "dry_run_default", True)
    st.session_state.workspace_dry_run_toggle = getattr(settings, "dry_run_default", True)
    st.session_state.workspace_batch_size = getattr(settings, "default_batch_size", 250)
    st.session_state.workspace_batch_size_slider = getattr(settings, "default_batch_size", 250)
    st.session_state.workspace_confidence_threshold = getattr(
        settings, "default_confidence_threshold", 0.65
    )
    st.session_state.workspace_confidence_slider = getattr(
        settings, "default_confidence_threshold", 0.65
    )
    st.session_state.workspace_limit = getattr(settings, "default_scan_limit", 500)
    st.session_state.workspace_limit_slider = getattr(settings, "default_scan_limit", 500)
    st.session_state.workspace_email_preview_limit = getattr(
        settings, "default_email_preview_limit", 120
    )
    st.session_state.workspace_email_preview_slider = getattr(
        settings, "default_email_preview_limit", 120
    )
    st.session_state.workspace_recommendation_preview_limit = getattr(
        settings, "default_recommendation_preview_limit", 180
    )
    st.session_state.workspace_recommendation_preview_slider = getattr(
        settings, "default_recommendation_preview_limit", 180
    )
    st.session_state.workspace_follow_up_enabled = getattr(
        settings, "follow_up_radar_enabled", True
    )
    st.session_state.workspace_follow_up_after_hours = getattr(
        settings, "follow_up_after_hours", 24
    )
    st.session_state.workspace_follow_up_priority_floor = getattr(
        settings, "follow_up_priority_floor", "medium"
    )


def _queue_workspace_notice(title: str, body: str, tone: str = "success") -> None:
    st.session_state.workspace_notice = {
        "title": title,
        "body": body,
        "tone": tone,
    }


def _apply_workspace_playbook(service: Any, slug: str):
    settings = _workspace_settings(service)
    playbook = _playbook_definition(slug)
    updated_policy = _copy_policy(settings.policy, playbook.get("policy", {}))
    updated_settings = _copy_settings(
        settings,
        {
            **playbook.get("settings", {}),
            "policy": updated_policy,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    saved = service.save_workspace_settings(updated_settings)
    _sync_workspace_control_state(saved)
    _queue_workspace_notice(
        f"{playbook['label']} applied",
        (
            f"{playbook['summary']} InboxAnchor updated the workspace defaults and policy "
            "for the next run."
        ),
        tone="success",
    )
    return saved


def _run_engine_compat(engine: Any, **kwargs):
    run_method = engine.run
    try:
        signature = inspect.signature(run_method)
    except (TypeError, ValueError):
        return run_method(**kwargs)
    filtered_kwargs = {
        name: value for name, value in kwargs.items() if name in signature.parameters
    }
    return run_method(**filtered_kwargs)


def _current_queue(service: Any, run_id: str) -> set[str]:
    return service.approvals.get(run_id, set())


def _queue_action(
    service: Any,
    *,
    run_id: str,
    email_id: str,
    should_queue: bool,
) -> None:
    queued = email_id in _current_queue(service, run_id)
    if should_queue and not queued:
        service.approve(run_id, [email_id])
    elif not should_queue and queued:
        service.reject(run_id, [email_id])


def _load_dashboard_data() -> tuple[list[dict], list]:
    with session_scope() as session:
        repository = _repository_class()(session)
        if hasattr(repository, "list_runs"):
            runs = repository.list_runs(limit=8)
        else:
            rows = (
                session.query(TriageRunORM)
                .order_by(TriageRunORM.started_at.desc())
                .limit(8)
                .all()
            )
            runs = [
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
        if hasattr(repository, "list_audit_entries"):
            audit_entries = repository.list_audit_entries()[:10]
        else:
            audit_entries = (
                session.query(AuditLogORM).order_by(AuditLogORM.timestamp.desc()).limit(10).all()
            )
    return runs, audit_entries


def _set_authenticated_session(token: str, user: AccountUser) -> None:
    st.session_state.auth_token = token
    st.session_state.auth_user = user.model_dump(mode="json")
    st.session_state.demo_access = False
    st.session_state.auth_view = "login"


def _clear_authenticated_session() -> None:
    st.session_state.pop("auth_token", None)
    st.session_state.pop("auth_user", None)


def _set_auth_view(view: str) -> None:
    if view in {"login", "signup", "demo"}:
        st.session_state.auth_view = view


def _current_account_user() -> Optional[AccountUser]:
    token = st.session_state.get("auth_token")
    if not token:
        _clear_authenticated_session()
        return None

    cached_user = st.session_state.get("auth_user")
    if cached_user:
        try:
            return AccountUser.model_validate(cached_user)
        except Exception:
            st.session_state.pop("auth_user", None)

    with session_scope() as session:
        auth_session = AuthService(session).get_session(token)

    if auth_session is None:
        _clear_authenticated_session()
        return None

    st.session_state.auth_user = auth_session.user.model_dump(mode="json")
    return auth_session.user


def _login_account(email: str, password: str) -> tuple[bool, str]:
    try:
        with session_scope() as session:
            auth_session = AuthService(session).authenticate(email=email, password=password)
        _set_authenticated_session(auth_session.token, auth_session.user)
        return True, "Signed in successfully."
    except AuthError as error:
        return False, error.message
    except Exception:
        return False, "Sign in is unavailable right now. Please try again in a moment."


def _signup_account(full_name: str, email: str, password: str) -> tuple[bool, str]:
    try:
        with session_scope() as session:
            auth_session = AuthService(session).register_user(
                full_name=full_name,
                email=email,
                password=password,
            )
        _set_authenticated_session(auth_session.token, auth_session.user)
        return True, "Account created successfully."
    except AuthError as error:
        return False, error.message
    except Exception:
        return False, "Account creation is unavailable right now. Please try again in a moment."


def _logout_account() -> None:
    token = st.session_state.get("auth_token")
    if token:
        try:
            with session_scope() as session:
                AuthService(session).logout(token)
        except Exception:
            pass
    _clear_authenticated_session()
    _set_auth_view("login")


def _render_auth_gate() -> bool:
    account_user = _current_account_user()
    if account_user is not None or st.session_state.get("demo_access", False):
        return True

    current_view = st.session_state.get("auth_view", "login")
    auth_index = {"login": 0, "signup": 1, "demo": 2}.get(current_view, 0)

    intro_col, auth_col = st.columns([1.04, 0.96], gap="medium")
    with intro_col:
        st.markdown(
            "\n".join(
                [
                    '<div class="ia-hero">',
                    (
                        "<div "
                        'style="font-size:0.8rem;letter-spacing:0.2em;'
                        'text-transform:uppercase;opacity:0.78;">InboxAnchor</div>'
                    ),
                    (
                        '<h1 style="margin:0.25rem 0 0.42rem 0;">'
                        "Turn inbox overload into a real operations workflow</h1>"
                    ),
                    (
                        '<p style="margin:0;max-width:760px;font-size:1rem;'
                        'line-height:1.58;opacity:0.94;">'
                        "Classify, prioritize, and clean up email safely with human approval, "
                        "audit trails, and provider-ready infrastructure."
                        "</p>"
                    ),
                    (
                        '<div style="margin-top:0.95rem;">'
                        '<span class="ia-chip ia-chip-dark">Account-aware</span>'
                        '<span class="ia-chip ia-chip-dark">Human approval</span>'
                        '<span class="ia-chip ia-chip-dark">Audit trail</span>'
                        '<span class="ia-chip ia-chip-dark">Demo ready</span>'
                        "</div>"
                    ),
                    "</div>",
                ]
            ),
            unsafe_allow_html=True,
        )
        render_metric_bar(
            [
                {"label": "Workspace", "value": "Private", "note": "Sign in to continue"},
                {"label": "Providers", "value": 5, "note": "Fake, Gmail, IMAP, Yahoo, Outlook"},
                {"label": "Safety", "value": "On", "note": "Approval-first workflow"},
                {"label": "Mode", "value": "Demo", "note": "Guest path still available"},
            ]
        )
    with auth_col:
        with st.container(border=True):
            st.markdown("#### Account Access")
            st.caption(
                "Use a real workspace account for a platform-style experience, or keep "
                "exploring in demo mode while the SaaS layer grows."
            )
            auth_view = st.radio(
                "Access mode",
                ["Log In", "Sign Up", "Demo Mode"],
                index=auth_index,
                horizontal=True,
                label_visibility="collapsed",
            )
            if auth_view == "Log In":
                _set_auth_view("login")
                with st.form("login_form"):
                    email = st.text_input(
                        "Email",
                        placeholder="name@company.com",
                    )
                    password = st.text_input(
                        "Password",
                        type="password",
                        placeholder="Enter your password",
                    )
                    st.caption("Secure sign-in for your private InboxAnchor workspace.")
                    submitted = st.form_submit_button("Log in", use_container_width=True)
                if submitted:
                    ok, message = _login_account(email, password)
                    if ok:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

            elif auth_view == "Sign Up":
                _set_auth_view("signup")
                with st.form("signup_form"):
                    identity_col1, identity_col2 = st.columns(2, gap="medium")
                    with identity_col1:
                        full_name = st.text_input(
                            "Full name",
                            placeholder="Luca Craciun",
                        )
                    with identity_col2:
                        email = st.text_input(
                            "Email",
                            placeholder="name@company.com",
                        )
                    st.markdown("##### Credentials")
                    password = st.text_input(
                        "Password",
                        type="password",
                        placeholder="Minimum 8 characters",
                    )
                    password_confirm = st.text_input(
                        "Confirm password",
                        type="password",
                        placeholder="Repeat password",
                    )
                    st.caption(
                        "Use a real email and a strong password. Passwords are hashed locally "
                        "before they are stored."
                    )
                    submitted = st.form_submit_button("Create account", use_container_width=True)
                if submitted:
                    if password != password_confirm:
                        st.error("Passwords do not match.")
                    else:
                        ok, message = _signup_account(full_name, email, password)
                        if ok:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)

            else:
                _set_auth_view("demo")
                render_callout(
                    "Guest preview",
                    (
                        "Demo mode keeps InboxAnchor fully explorable with seeded mailbox data. "
                        "You can come back and create an account whenever you want the full "
                        "platform-style flow."
                    ),
                    tone="info",
                )
                if st.button("Continue as demo guest", type="primary", use_container_width=True):
                    st.session_state.demo_access = True
                    st.rerun()
    return False


def _render_provider_profile(provider_name: str, service: Any) -> None:
    profile = _provider_profile(provider_name)
    connection = _provider_connection_state(service, provider_name)
    card_open("Provider Readiness", f"{profile.label} · {profile.status}")
    render_pill_row(
        [
            (profile.family, "chip"),
            (profile.auth_mode, "chip"),
            (
                "live ready" if profile.live_ready else "setup required",
                "safe" if profile.live_ready else "review",
            ),
            (
                connection.status.replace("_", " "),
                "review" if connection.status != "connected" else "safe",
            ),
        ]
    )
    st.write(profile.best_for)
    if connection.account_hint:
        st.caption(f"Workspace: {connection.account_hint}")
    if connection.last_tested_at:
        st.caption(f"Last verified: {connection.last_tested_at}")
    st.markdown("**Capabilities**")
    for item in profile.capabilities:
        st.write(f"- {item}")
    st.markdown("**Safety notes**")
    for note in profile.safety_notes:
        st.caption(note)
    card_close()


def _render_workspace_settings_panel(service: Any) -> None:
    settings = _workspace_settings(service)
    card_open("Workspace Settings", "Saved defaults for every future triage run.")
    with st.form("workspace_settings_form"):
        top_row = st.columns(2, gap="medium")
        with top_row[0]:
            preferred_provider = st.selectbox(
                "Preferred provider",
                _provider_options(),
                index=_provider_options().index(settings.preferred_provider)
                if settings.preferred_provider in _provider_options()
                else 0,
            )
        with top_row[1]:
            operator_mode = st.selectbox(
                "Operator mode",
                ["safe", "balanced", "aggressive"],
                index=["safe", "balanced", "aggressive"].index(
                    getattr(settings, "operator_mode", "safe")
                ),
            )
        dry_run_default = st.toggle(
            "Default to dry run",
            value=getattr(settings, "dry_run_default", True),
        )

        middle_row = st.columns(2, gap="medium")
        with middle_row[0]:
            default_scan_limit = st.slider(
                "Default scan window",
                min_value=25,
                max_value=10000,
                value=getattr(settings, "default_scan_limit", 500),
                step=25,
            )
        with middle_row[1]:
            default_batch_size = st.select_slider(
                "Default batch size",
                options=[100, 250, 500, 1000],
                value=getattr(settings, "default_batch_size", 250),
            )
        default_confidence_threshold = st.slider(
            "Default confidence floor",
            min_value=0.0,
            max_value=1.0,
            value=getattr(settings, "default_confidence_threshold", 0.65),
            step=0.05,
        )

        preview_row = st.columns(2, gap="medium")
        with preview_row[0]:
            default_email_preview_limit = st.slider(
                "Default email preview cap",
                min_value=10,
                max_value=500,
                value=getattr(settings, "default_email_preview_limit", 120),
                step=10,
            )
        with preview_row[1]:
            default_recommendation_preview_limit = st.slider(
                "Default recommendation preview cap",
                min_value=10,
                max_value=1000,
                value=getattr(settings, "default_recommendation_preview_limit", 180),
                step=10,
            )

        follow_up_row = st.columns(2, gap="medium")
        with follow_up_row[0]:
            follow_up_radar_enabled = st.toggle(
                "Enable follow-up radar",
                value=getattr(settings, "follow_up_radar_enabled", True),
            )
        with follow_up_row[1]:
            follow_up_priority_floor = st.selectbox(
                "Follow-up priority floor",
                ["critical", "high", "medium", "low"],
                index=["critical", "high", "medium", "low"].index(
                    getattr(settings, "follow_up_priority_floor", "medium")
                ),
            )
        follow_up_after_hours = st.slider(
            "Resurface follow-ups after (hours)",
            min_value=1,
            max_value=240,
            value=getattr(settings, "follow_up_after_hours", 24),
            step=1,
        )

        onboarding_completed = st.toggle(
            "Onboarding completed",
            value=getattr(settings, "onboarding_completed", False),
        )
        submitted = st.form_submit_button("Save workspace defaults", type="primary")

    if submitted:
        saved = service.save_workspace_settings(
            _copy_settings(
                settings,
                {
                    "preferred_provider": preferred_provider,
                    "operator_mode": operator_mode,
                    "dry_run_default": dry_run_default,
                    "default_scan_limit": default_scan_limit,
                    "default_batch_size": default_batch_size,
                    "default_confidence_threshold": default_confidence_threshold,
                    "default_email_preview_limit": default_email_preview_limit,
                    "default_recommendation_preview_limit": default_recommendation_preview_limit,
                    "follow_up_radar_enabled": follow_up_radar_enabled,
                    "follow_up_after_hours": follow_up_after_hours,
                    "follow_up_priority_floor": follow_up_priority_floor,
                    "onboarding_completed": onboarding_completed,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
        )
        _sync_workspace_control_state(saved)
        render_callout(
            "Workspace defaults saved",
            "Future triage runs will start from these settings unless you override them.",
            tone="success",
        )
    card_close()


def _render_policy_studio(service: Any) -> None:
    settings = _workspace_settings(service)
    policy = settings.policy
    card_open("Policy Studio", "Control how aggressive cleanup can be before humans step in.")
    with st.form("policy_studio_form"):
        policy_top = st.columns(2, gap="medium")
        with policy_top[0]:
            newsletter_confidence_threshold = st.slider(
                "Newsletter cleanup threshold",
                min_value=0.5,
                max_value=1.0,
                value=getattr(policy, "newsletter_confidence_threshold", 0.9),
                step=0.05,
            )
        with policy_top[1]:
            promo_archive_age_days = st.slider(
                "Promo archive age (days)",
                min_value=1,
                max_value=60,
                value=getattr(policy, "promo_archive_age_days", 14),
                step=1,
            )
        low_priority_age_days = st.slider(
            "Low-priority cleanup age (days)",
            min_value=1,
            max_value=30,
            value=getattr(policy, "low_priority_age_days", 7),
            step=1,
        )

        toggle_row_one = st.columns(2, gap="medium")
        with toggle_row_one[0]:
            allow_newsletter_mark_read = st.toggle(
                "Allow newsletter mark-as-read",
                value=getattr(policy, "allow_newsletter_mark_read", True),
            )
        with toggle_row_one[1]:
            allow_promo_archive = st.toggle(
                "Allow promo archive",
                value=getattr(policy, "allow_promo_archive", True),
            )
        allow_low_priority_cleanup = st.toggle(
            "Allow low-priority cleanup",
            value=getattr(policy, "allow_low_priority_cleanup", True),
        )

        toggle_row_two = st.columns(2, gap="medium")
        with toggle_row_two[0]:
            allow_spam_trash_recommendations = st.toggle(
                "Allow spam trash recommendations",
                value=getattr(policy, "allow_spam_trash_recommendations", True),
            )
        with toggle_row_two[1]:
            auto_label_recommendations = st.toggle(
                "Auto-label recommendations",
                value=getattr(policy, "auto_label_recommendations", True),
            )
        second_toggle_row = st.columns(2, gap="medium")
        with second_toggle_row[0]:
            require_review_for_attachments = st.toggle(
                "Attachments always require review",
                value=getattr(policy, "require_review_for_attachments", True),
            )
        with second_toggle_row[1]:
            require_review_for_finance = st.toggle(
                "Finance mail always requires review",
                value=getattr(policy, "require_review_for_finance", True),
            )

        require_review_for_personal = st.toggle(
            "Personal mail always requires review",
            value=getattr(policy, "require_review_for_personal", True),
        )
        submitted = st.form_submit_button("Save policy", type="primary")

    if submitted:
        updated_policy = _copy_policy(
            policy,
            {
                "newsletter_confidence_threshold": newsletter_confidence_threshold,
                "promo_archive_age_days": promo_archive_age_days,
                "low_priority_age_days": low_priority_age_days,
                "allow_newsletter_mark_read": allow_newsletter_mark_read,
                "allow_promo_archive": allow_promo_archive,
                "allow_low_priority_cleanup": allow_low_priority_cleanup,
                "allow_spam_trash_recommendations": allow_spam_trash_recommendations,
                "auto_label_recommendations": auto_label_recommendations,
                "require_review_for_attachments": require_review_for_attachments,
                "require_review_for_finance": require_review_for_finance,
                "require_review_for_personal": require_review_for_personal,
            },
        )
        service.save_workspace_settings(
            _copy_settings(
                settings,
                {
                    "policy": updated_policy,
                    "updated_at": datetime.now(timezone.utc),
                },
            )
        )
        render_callout(
            "Policy updated",
            "InboxAnchor will use the new cleanup and review rules on the next triage run.",
            tone="success",
        )
    card_close()


def _render_provider_setup_panel(service: Any, provider_name: str) -> None:
    connection = _provider_connection_state(service, provider_name)
    profile = _provider_profile(provider_name)
    card_open("Provider Setup", "Track how ready each mailbox provider is for real use.")
    with st.form(f"provider_setup_{provider_name}"):
        account_hint = st.text_input("Account hint", value=getattr(connection, "account_hint", ""))
        status = st.selectbox(
            "Connection status",
            CONNECTION_STATUS_OPTIONS,
            index=CONNECTION_STATUS_OPTIONS.index(connection.status)
            if connection.status in CONNECTION_STATUS_OPTIONS
            else 0,
        )
        sync_row = st.columns(2, gap="medium")
        with sync_row[0]:
            sync_enabled = st.toggle(
                "Sync enabled",
                value=getattr(connection, "sync_enabled", False),
            )
        with sync_row[1]:
            dry_run_only = st.toggle(
                "Dry-run only",
                value=getattr(connection, "dry_run_only", True),
            )
        notes = st.text_area(
            "Setup notes",
            value=getattr(connection, "notes", ""),
            placeholder=(
                "Example: Gmail OAuth planned next, Yahoo uses app-password testing, "
                "or keep this provider demo-only for now."
            ),
        )
        submitted = st.form_submit_button("Save provider state", type="primary")

    st.caption(f"{profile.label} auth mode: {profile.auth_mode}")
    if submitted:
        saved = service.save_provider_connection(
            _copy_provider_connection(
                connection,
                {
                    "provider": provider_name,
                    "account_hint": account_hint,
                    "status": status,
                    "sync_enabled": sync_enabled,
                    "dry_run_only": dry_run_only,
                    "notes": notes,
                    "last_tested_at": datetime.now(timezone.utc),
                },
            )
        )
        render_callout(
            "Provider state saved",
            f"{saved.provider.upper()} is now tracked as {saved.status.replace('_', ' ')}.",
            tone="success",
        )
    card_close()


def _crew_status(result: Optional[TriageRunResult]) -> tuple[str, str]:
    if result is None:
        return (
            "review",
            (
                "The crew is ready to scan a mailbox, surface signal, and hold "
                "risky actions for review."
            ),
        )
    if result.blocked_actions:
        return (
            "blocked",
            (
                "The crew found risky or policy-blocked paths and is keeping "
                "those actions behind safeguards."
            ),
        )
    if result.approvals_required:
        return (
            "review",
            (
                "The crew has recommendations ready, but some actions still need "
                "explicit operator approval."
            ),
        )
    return (
        "safe",
        (
            "The crew finished a low-risk pass and the current workspace is "
            "ready for supervised execution."
        ),
    )


def _hero(result: Optional[TriageRunResult], service: Any) -> None:
    account_user = _current_account_user()
    demo_access = st.session_state.get("demo_access", False)
    if result is None:
        highlights = [
            ("Safe-by-default", "chip"),
            ("Human approval", "chip"),
            ("Audit trail", "chip"),
            ("Provider-ready", "chip"),
        ]
        subtitle = (
            "Turn inbox overload into a controlled operations workflow. "
            "InboxAnchor classifies, prioritizes, and recommends actions before "
            "any mailbox change is allowed."
        )
    else:
        queued_count = len(_current_queue(service, result.run_id))
        highlights = [
            (f"{result.provider.upper()} provider", "chip"),
            (f"{result.scanned_emails} scanned", "chip"),
            (f"{result.total_emails} retained", "chip"),
            (f"{queued_count} queued actions", "chip"),
        ]
        subtitle = result.digest.summary

    chips = "".join(
        f'<span class="ia-chip ia-chip-dark">{label}</span>' for label, _ in highlights
    )
    hero_col, account_col = st.columns([1.06, 0.54], gap="medium")
    with hero_col:
        st.markdown(
            "\n".join(
                [
                    '<div class="ia-hero">',
                    (
                        "<div "
                        'style="font-size:0.8rem;letter-spacing:0.2em;'
                        'text-transform:uppercase;opacity:0.78;">InboxAnchor</div>'
                    ),
                    (
                        '<h1 style="margin:0.25rem 0 0.42rem 0;">'
                        "The safe inbox operations workspace</h1>"
                    ),
                    (
                        '<p style="margin:0;max-width:820px;font-size:1rem;'
                        'line-height:1.58;opacity:0.94;">'
                    ),
                    subtitle,
                    "</p>",
                    f'<div style="margin-top:0.95rem;">{chips}</div>',
                    "</div>",
                ]
            ),
            unsafe_allow_html=True,
        )
    with account_col:
        with st.container(border=True):
            if account_user is not None:
                st.markdown("#### Account")
                render_pill_row([("signed in", "safe"), (account_user.plan, "chip")])
                st.write(account_user.full_name)
                st.caption(account_user.email)
                st.caption("Your workspace state stays private to this account session.")
                if st.button("Log out securely", use_container_width=True):
                    _logout_account()
                    st.rerun()
            elif demo_access:
                st.markdown("#### Demo Guest")
                render_pill_row([("demo mode", "review"), ("not saved", "chip")])
                st.caption(
                    "You are exploring InboxAnchor without an account. Create one when "
                    "you want the full platform-style flow."
                )
                action_col1, action_col2 = st.columns(2, gap="small")
                with action_col1:
                    if st.button("Log In", use_container_width=True):
                        st.session_state.demo_access = False
                        st.session_state.auth_view = "login"
                        st.rerun()
                with action_col2:
                    if st.button("Sign Up", use_container_width=True):
                        st.session_state.demo_access = False
                        st.session_state.auth_view = "signup"
                        st.rerun()
            else:
                st.markdown("#### Workspace Access")
                render_pill_row(
                    [
                        ("authentication required", "review"),
                        ("private workspace", "chip"),
                    ]
                )
                st.caption(
                    "Create an account or sign in from the panel below to unlock a persistent "
                    "workspace experience."
                )


def _metric_snapshot(result: Optional[TriageRunResult], service: Any) -> None:
    if result is None:
        render_metric_bar(
            [
                {
                    "label": "Provider",
                    "value": service.provider.provider_name.upper(),
                    "note": "Ready",
                },
                {"label": "Scanned", "value": 0, "note": "Awaiting first run"},
                {"label": "Retained", "value": 0, "note": "Awaiting first run"},
                {"label": "Queued", "value": 0, "note": "Nothing queued yet"},
            ]
        )
        return

    recommendations = result.recommendations
    safe_count = sum(1 for item in recommendations if item.status == RecommendationStatus.safe)
    review_count = sum(
        1 for item in recommendations if item.status == RecommendationStatus.requires_approval
    )
    blocked_count = sum(
        1 for item in recommendations if item.status == RecommendationStatus.blocked
    )
    queued_count = len(_current_queue(service, result.run_id))

    render_metric_bar(
        [
            {
                "label": "Provider",
                "value": result.provider.upper(),
                "note": f"{result.batch_count} scan batches",
                "tone": "primary",
            },
            {
                "label": "Scanned",
                "value": result.scanned_emails,
                "note": "Unread messages inspected",
            },
            {
                "label": "Retained",
                "value": result.total_emails,
                "note": "After confidence and category filters",
            },
            {
                "label": "Queued",
                "value": queued_count,
                "note": "Ready for supervised execution",
                "tone": "success" if queued_count else "neutral",
            },
            {
                "label": "Safe",
                "value": safe_count,
                "note": "Low-risk recommendations",
                "tone": "success",
            },
            {
                "label": "Review",
                "value": review_count,
                "note": "Approval required",
                "tone": "warning",
            },
            {
                "label": "Blocked",
                "value": blocked_count,
                "note": "Stopped by policy",
                "tone": "danger",
            },
        ]
    )


def _render_category_counts(result: TriageRunResult) -> None:
    if not result.digest.category_counts:
        st.info("No category data yet.")
        return
    render_pill_row(
        [
            (f"{category}: {count}", "chip")
            for category, count in sorted(result.digest.category_counts.items())
        ]
    )


def _render_scale_summary(result: TriageRunResult) -> None:
    if not (result.email_preview_truncated or result.recommendation_preview_truncated):
        render_callout(
            "Full preview loaded",
            "This run is fully rendered in the workspace without preview trimming.",
            tone="success",
        )
        return

    notes: list[str] = []
    if result.email_preview_truncated:
        notes.append(
            f"showing {len(result.emails)} preview emails while preserving "
            f"{result.total_emails} retained records in storage"
        )
    if result.recommendation_preview_truncated:
        notes.append(
            "recommendation rendering is capped to keep the app responsive on large inboxes"
        )
    render_callout(
        "Large inbox preview mode",
        "; ".join(notes) + ". Full detail remains available through history and audit data.",
        tone="warning",
    )


def _render_inbox_overview(result: TriageRunResult) -> None:
    card_open("Inbox Overview", "Digest intelligence generated from the latest triage pass.")
    _render_scale_summary(result)
    st.markdown("**Daily digest**")
    st.write(result.digest.daily_digest)
    st.markdown("**Weekly roll-up**")
    st.caption(result.digest.weekly_digest)
    card_close()


def _render_run_health(result: TriageRunResult, service: Any) -> None:
    queued_count = len(_current_queue(service, result.run_id))
    card_open("Approval Center", "Queue low-risk actions and execute them with full traceability.")
    render_pill_row(
        [
            (f"{queued_count} queued", "neutral"),
            (f"{len(result.approvals_required)} review required", "review"),
            (f"{len(result.blocked_actions)} blocked", "blocked"),
        ]
    )
    st.caption(
        "InboxAnchor never sends replies automatically, never trashes mail without explicit "
        "confirmation, and keeps an audit trail for every executed action."
    )
    allow_trash = st.toggle(
        "Allow approved trash actions in this execution",
        value=False,
        key=f"trash_confirm_{result.run_id}",
    )
    with st.popover("Execution policy"):
        st.markdown(
            "\n".join(
                [
                    "- Safe actions can be queued directly.",
                    "- Review-required actions must be explicitly approved.",
                    "- Trash remains blocked unless this extra confirmation is enabled.",
                    "- Executed actions are written to the audit log immediately.",
                ]
            )
        )
    if st.button(
        "Execute queued actions",
        type="primary",
        use_container_width=True,
        disabled=queued_count == 0,
    ):
        decisions = service.engine.execute_actions(
            result,
            approved_email_ids=sorted(_current_queue(service, result.run_id)),
            explicit_trash_confirmation=allow_trash,
        )
        st.session_state.execution_results = decisions
        st.session_state.execution_flash = (
            f"Processed {len(decisions)} queued actions for run {result.run_id}."
        )
        st.rerun()

    latest_decisions = st.session_state.get("execution_results", [])
    if latest_decisions:
        st.markdown("**Last execution**")
        for decision in latest_decisions[:5]:
            st.caption(
                f"{decision.email_id} · {decision.proposed_action} → {decision.final_action}"
            )
    card_close()


def _render_recommendation_lane_summary(recommendations: Iterable[EmailRecommendation]) -> None:
    recommendations = list(recommendations)
    safe_count = sum(1 for item in recommendations if item.status == RecommendationStatus.safe)
    review_count = sum(
        1 for item in recommendations if item.status == RecommendationStatus.requires_approval
    )
    blocked_count = sum(
        1 for item in recommendations if item.status == RecommendationStatus.blocked
    )
    render_pill_row(
        [
            (f"{safe_count} safe", "safe"),
            (f"{review_count} review", "review"),
            (f"{blocked_count} blocked", "blocked"),
        ]
    )


def _queue_many_actions(
    service: Any,
    run_id: str,
    email_ids: Iterable[str],
    should_queue: bool,
) -> None:
    ids = sorted(set(email_ids))
    if not ids:
        return
    if should_queue:
        service.approve(run_id, ids)
    else:
        service.reject(run_id, ids)


def _recommendation_tone(status: RecommendationStatus) -> str:
    if status == RecommendationStatus.safe:
        return "safe"
    if status == RecommendationStatus.requires_approval:
        return "review"
    return "blocked"


def _render_single_recommendation(
    result: TriageRunResult,
    item: EmailRecommendation,
    service: Any,
) -> None:
    email_lookup = {email.id: email for email in result.emails}
    classification_lookup = result.classifications
    email = email_lookup.get(item.email_id)
    classification = classification_lookup.get(item.email_id)
    tone = _recommendation_tone(item.status)
    subject = email.subject if email else f"Email {item.email_id}"
    sender = email.sender if email else "Preview-only recommendation"
    queued = item.email_id in _current_queue(service, result.run_id)

    with st.container(border=True):
        header_col, meta_col = st.columns([0.72, 0.28], gap="medium")
        with header_col:
            st.markdown(f"**{subject}**")
            st.caption(sender)
            pills: list[tuple[str, str]] = [
                (item.recommended_action.replace("_", " "), tone),
                (f"{item.confidence:.0%} confidence", "neutral"),
            ]
            if classification is not None:
                pills.append((str(classification.priority).upper(), tone))
                pills.append((str(classification.category), "chip"))
            render_pill_row(pills)
            st.write(item.reason)
            if item.proposed_labels:
                st.caption(f"Proposed labels: {', '.join(item.proposed_labels)}")

        with meta_col:
            with st.popover("Inspect"):
                st.markdown(f"**Email ID**: `{item.email_id}`")
                if email is not None:
                    st.markdown(f"**Received**: {email.received_at.isoformat()}")
                    st.markdown(f"**Attachments**: {'yes' if email.has_attachments else 'no'}")
                    st.markdown(f"**Snippet**: {email.snippet}")
                if classification is not None:
                    st.markdown(
                        f"**Classification**: {classification.category} / "
                        f"{classification.priority}"
                    )
                    st.markdown(f"**Why**: {classification.reason}")
                if item.blocked_reason:
                    st.markdown(f"**Blocked reason**: {item.blocked_reason}")

            if item.status == RecommendationStatus.blocked:
                st.warning(item.blocked_reason or "Blocked by safety policy.")
                return

            label = "Queue action" if item.status == RecommendationStatus.safe else "Approve action"
            should_queue = st.toggle(
                label,
                value=queued,
                key=f"queue_{result.run_id}_{item.email_id}",
            )
            _queue_action(
                service,
                run_id=result.run_id,
                email_id=item.email_id,
                should_queue=should_queue,
            )


def _render_recommendations(result: TriageRunResult, service: Any) -> None:
    safe = [item for item in result.recommendations if item.status == RecommendationStatus.safe]
    gated = [
        item
        for item in result.recommendations
        if item.status == RecommendationStatus.requires_approval
    ]
    blocked = [
        item for item in result.recommendations if item.status == RecommendationStatus.blocked
    ]

    card_open(
        "Decision Lanes",
        "Each recommendation is separated into safe, review-required, and blocked lanes.",
    )
    _render_recommendation_lane_summary(result.recommendations)
    st.caption(
        "Queue safe actions directly, approve higher-risk actions deliberately, and inspect "
        "blocked items without losing the audit trail."
    )
    action_row = st.columns(3, gap="small")
    with action_row[0]:
        if st.button(
            "Queue all safe cleanup",
            use_container_width=True,
            key=f"queue_safe_lane_{result.run_id}",
            disabled=not safe,
        ):
            _queue_many_actions(
                service,
                result.run_id,
                [item.email_id for item in safe],
                True,
            )
            st.rerun()
    with action_row[1]:
        if st.button(
            "Approve all review items",
            use_container_width=True,
            key=f"queue_review_lane_{result.run_id}",
            disabled=not gated,
        ):
            _queue_many_actions(
                service,
                result.run_id,
                [item.email_id for item in gated],
                True,
            )
            st.rerun()
    with action_row[2]:
        if st.button(
            "Clear queued lane actions",
            use_container_width=True,
            key=f"clear_lane_queue_{result.run_id}",
            disabled=not _current_queue(service, result.run_id),
        ):
            _queue_many_actions(
                service,
                result.run_id,
                list(_current_queue(service, result.run_id)),
                False,
            )
            st.rerun()
    tabs = st.tabs(["Safe Cleanup", "Requires Review", "Blocked by Policy"])
    for tab, items in zip(tabs, [safe, gated, blocked]):
        with tab:
            if not items:
                st.success("Nothing in this lane.")
                continue
            for item in items:
                _render_single_recommendation(result, item, service)
    card_close()


def _render_priority_queue(result: TriageRunResult) -> None:
    card_open("Priority Queue", "What the operator should read or reply to first.")
    important = []
    for email in result.emails:
        classification = result.classifications[email.id]
        if str(classification.priority) in {"critical", "high"}:
            important.append((email, classification))

    if not important:
        st.info("No high-priority items in the current preview.")
        card_close()
        return

    for email, classification in important[:8]:
        with st.container(border=True):
            st.markdown(f"**{email.subject}**")
            render_pill_row(
                [
                    (str(classification.priority).upper(), "review"),
                    (str(classification.category), "chip"),
                ]
            )
            st.caption(email.sender)
            st.write(classification.reason)
    card_close()


def _focus_rank(classification: Any, email: Any) -> tuple[int, float]:
    priority_value = str(getattr(classification, "priority", "medium"))
    priority_rank = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }.get(priority_value, 4)
    return (priority_rank, -email.received_at.timestamp())


def _priority_meets_floor(priority: str, floor: str) -> bool:
    priority_order = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "low": 3,
    }
    return priority_order.get(priority, 4) <= priority_order.get(floor, 2)


def _build_focus_views(result: TriageRunResult) -> dict[str, list[dict[str, Any]]]:
    recommendation_map = {item.email_id: item for item in result.recommendations}
    views = {
        "reply_now": [],
        "needs_approval": [],
        "sensitive": [],
        "cleanup": [],
    }
    sensitive_categories = {"finance", "personal", "opportunity", "urgent"}
    reply_action_types = {"reply_needed", "follow_up", "deadline", "invoice_payment"}

    for email in result.emails:
        classification = result.classifications[email.id]
        recommendation = recommendation_map.get(email.id)
        items = result.action_items.get(email.id, [])
        action_types = {item.action_type for item in items}
        requires_reply = any(item.requires_reply for item in items)
        has_draft = email.id in result.reply_drafts
        is_sensitive = (
            email.has_attachments
            or str(classification.category) in sensitive_categories
            or (
                recommendation is not None
                and recommendation.status == RecommendationStatus.blocked
            )
        )
        cleanup_candidate = (
            recommendation is not None
            and recommendation.status == RecommendationStatus.safe
            and recommendation.recommended_action
            in {"mark_read", "archive", "trash", "apply_labels"}
        )
        approval_candidate = (
            recommendation is not None
            and recommendation.status == RecommendationStatus.requires_approval
        )
        reply_candidate = (
            str(classification.priority) in {"critical", "high"}
            or requires_reply
            or has_draft
            or bool(action_types & reply_action_types)
        )
        entry = {
            "email": email,
            "classification": classification,
            "recommendation": recommendation,
            "items": items,
            "has_draft": has_draft,
            "requires_reply": requires_reply,
        }
        if reply_candidate:
            views["reply_now"].append(entry)
        if approval_candidate:
            views["needs_approval"].append(entry)
        if is_sensitive:
            views["sensitive"].append(entry)
        if cleanup_candidate:
            views["cleanup"].append(entry)

    for key in views:
        views[key] = sorted(
            views[key],
            key=lambda entry: _focus_rank(entry["classification"], entry["email"]),
        )
    return views


def _build_follow_up_radar(result: TriageRunResult, settings: Any) -> list[dict[str, Any]]:
    if not getattr(settings, "follow_up_radar_enabled", True):
        return []

    threshold_hours = getattr(settings, "follow_up_after_hours", 24)
    priority_floor = getattr(settings, "follow_up_priority_floor", "medium")
    recommendation_map = {item.email_id: item for item in result.recommendations}
    now = datetime.now(timezone.utc)
    radar_entries: list[dict[str, Any]] = []

    for email in result.emails:
        classification = result.classifications[email.id]
        items = result.action_items.get(email.id, [])
        recommendation = recommendation_map.get(email.id)
        age_hours = max(
            0,
            int((now - email.received_at).total_seconds() // 3600),
        )
        has_follow_up_signal = (
            any(item.requires_reply for item in items)
            or any(item.action_type in {"reply_needed", "follow_up", "deadline"} for item in items)
            or email.id in result.reply_drafts
            or (
                recommendation is not None
                and recommendation.status == RecommendationStatus.requires_approval
            )
        )
        if not has_follow_up_signal:
            continue
        if age_hours < threshold_hours:
            continue
        if not _priority_meets_floor(str(classification.priority), priority_floor):
            continue

        radar_entries.append(
            {
                "email": email,
                "classification": classification,
                "recommendation": recommendation,
                "items": items,
                "age_hours": age_hours,
                "has_draft": email.id in result.reply_drafts,
            }
        )

    return sorted(
        radar_entries,
        key=lambda entry: (
            -entry["age_hours"],
            *_focus_rank(entry["classification"], entry["email"]),
        ),
    )


def _render_focus_entry(entry: dict[str, Any], tone: str) -> None:
    email = entry["email"]
    classification = entry["classification"]
    recommendation = entry.get("recommendation")
    items = entry.get("items", [])
    pills = [
        (str(classification.priority).upper(), tone),
        (str(classification.category), "chip"),
    ]
    if recommendation is not None:
        pills.append((recommendation.recommended_action.replace("_", " "), tone))
    if entry.get("has_draft"):
        pills.append(("draft ready", "safe"))
    if items:
        pills.append((f"{len(items)} action item(s)", "chip"))
    if email.has_attachments:
        pills.append(("attachments", "review"))

    with st.container(border=True):
        st.markdown(f"**{email.subject}**")
        render_pill_row(pills)
        st.caption(email.sender)
        if recommendation is not None:
            st.write(recommendation.reason)
        else:
            st.write(classification.reason)
        st.caption(email.snippet)


def _render_focus_inbox(result: TriageRunResult) -> None:
    focus_views = _build_focus_views(result)
    card_open(
        "Focus Inbox",
        (
            "Split the current run into response pressure, approvals, sensitive mail, "
            "and cleanup work."
        ),
    )
    render_pill_row(
        [
            (f"{len(focus_views['reply_now'])} reply now", "review"),
            (f"{len(focus_views['needs_approval'])} approvals", "review"),
            (f"{len(focus_views['sensitive'])} sensitive", "blocked"),
            (f"{len(focus_views['cleanup'])} cleanup", "safe"),
        ]
    )
    st.caption(
        "This is InboxAnchor's answer to split inboxes and follow-up reminders: one surface "
        "for what needs a reply, what needs a human decision, and what is safe to clear."
    )
    tabs = st.tabs(["Reply Now", "Needs Approval", "Sensitive", "Cleanup"])
    tab_map = [
        ("reply_now", "review", "Nothing urgent is asking for a reply in this preview."),
        (
            "needs_approval",
            "review",
            "No recommendation currently needs manual approval.",
        ),
        ("sensitive", "blocked", "No sensitive or blocked items are in the preview."),
        ("cleanup", "safe", "No low-risk cleanup candidates are ready right now."),
    ]
    for tab, (view_key, tone, empty_message) in zip(tabs, tab_map):
        with tab:
            entries = focus_views[view_key]
            if not entries:
                st.info(empty_message)
                continue
            for entry in entries[:8]:
                _render_focus_entry(entry, tone)
    card_close()


def _render_follow_up_radar(result: TriageRunResult, settings: Any) -> None:
    radar_entries = _build_follow_up_radar(result, settings)
    threshold_hours = getattr(settings, "follow_up_after_hours", 24)
    priority_floor = getattr(settings, "follow_up_priority_floor", "medium")
    card_open(
        "Follow-Up Radar",
        (
            "Resurface reply pressure before it goes cold. This is tuned from workspace "
            "settings and only highlights stale threads that still deserve operator attention."
        ),
    )
    render_pill_row(
        [
            (
                "enabled" if getattr(settings, "follow_up_radar_enabled", True) else "disabled",
                "chip",
            ),
            (f"{threshold_hours}h threshold", "chip"),
            (f"{priority_floor}+ priority", "review"),
            (f"{len(radar_entries)} surfaced", "review" if radar_entries else "neutral"),
        ]
    )
    if not getattr(settings, "follow_up_radar_enabled", True):
        st.info("Follow-up radar is disabled in workspace settings.")
        card_close()
        return
    if not radar_entries:
        st.info("No stale follow-ups are above the current reminder threshold.")
        card_close()
        return

    for entry in radar_entries[:8]:
        email = entry["email"]
        classification = entry["classification"]
        recommendation = entry.get("recommendation")
        items = entry.get("items", [])
        pills = [
            (f"{entry['age_hours']}h old", "review"),
            (str(classification.priority).upper(), "review"),
            (str(classification.category), "chip"),
        ]
        if entry.get("has_draft"):
            pills.append(("draft ready", "safe"))
        if recommendation is not None:
            pills.append((recommendation.recommended_action.replace("_", " "), "chip"))
        with st.container(border=True):
            st.markdown(f"**{email.subject}**")
            render_pill_row(pills)
            st.caption(email.sender)
            if items:
                st.write(items[0].description)
            elif recommendation is not None:
                st.write(recommendation.reason)
            else:
                st.write(classification.reason)
            st.caption(email.snippet)
    card_close()


def _render_action_items(result: TriageRunResult) -> None:
    card_open("Action Items", "Follow-ups, scheduling, finance, and review tasks extracted.")
    found = False
    for email in result.emails:
        items = result.action_items.get(email.id, [])
        if not items:
            continue
        found = True
        with st.expander(f"{email.subject} · {len(items)} item(s)"):
            for item in items:
                st.write(f"- `{item.action_type}` — {item.description}")
    if not found:
        st.info("No action items extracted in this run.")
    card_close()


def _render_suggested_replies(result: TriageRunResult) -> None:
    card_open("Suggested Replies", "Helpful drafts only. InboxAnchor never sends automatically.")
    if result.reply_drafts:
        for email_id, draft in result.reply_drafts.items():
            email = next((item for item in result.emails if item.id == email_id), None)
            title = email.subject if email else email_id
            with st.expander(title):
                st.code(draft, language="markdown")
    else:
        st.info("No replies drafted for this run.")
    card_close()


def _render_run_history(runs: list[dict]) -> None:
    card_open("Run History", "Recent triage passes and their scale profile.")
    if not runs:
        st.info("Run history will appear here after the first triage pass.")
        card_close()
        return

    for run in runs:
        with st.container(border=True):
            st.markdown(
                f"**{run['run_id']}** · `{run['provider']}` · "
                f"{run['scanned_emails']} scanned / {run['total_emails']} retained"
            )
            render_pill_row(
                [
                    (f"{run['batch_count']} batches", "chip"),
                    (f"{len(run['approvals_required'])} approvals", "review"),
                    (f"{len(run['blocked_actions'])} blocked", "blocked"),
                ]
            )
            st.caption(run["started_at"])
            st.write(run["digest_summary"])
            if run.get("email_preview_truncated") or run.get(
                "recommendation_preview_truncated"
            ):
                st.caption("Preview-capped for dashboard responsiveness.")
    card_close()


def _render_audit_log(audit_entries: list) -> None:
    card_open("Audit Timeline", "Every executed action remains searchable and explainable.")
    if not audit_entries:
        st.info("Audit entries appear after queued actions are executed.")
        card_close()
        return

    for entry in audit_entries:
        with st.container(border=True):
            st.markdown(f"**{entry.email_id}** · `{entry.final_action}`")
            render_pill_row(
                [
                    (
                        "approved" if entry.approved_by_user else "not approved",
                        "neutral" if entry.approved_by_user else "blocked",
                    ),
                    (str(entry.safety_verifier_status), "chip"),
                ]
            )
            st.caption(entry.timestamp.isoformat())
            st.write(entry.reason)
    card_close()


def _render_run_explorer(result: TriageRunResult, runs: list[dict]) -> None:
    card_open(
        "Run Explorer",
        "Inspect stored records behind large runs without relying only on the live preview.",
    )
    if not runs:
        st.info("Run history must exist before the explorer becomes useful.")
        card_close()
        return

    selected_run_id = st.selectbox(
        "Explore run",
        [run["run_id"] for run in runs],
        index=(
            0
            if result.run_id not in {run["run_id"] for run in runs}
            else [run["run_id"] for run in runs].index(result.run_id)
        ),
    )
    selected_run = next(run for run in runs if run["run_id"] == selected_run_id)
    render_metric_bar(
        [
            {
                "label": "Scanned",
                "value": selected_run["scanned_emails"],
                "note": "Total messages inspected",
            },
            {
                "label": "Retained",
                "value": selected_run["total_emails"],
                "note": "Records kept after filters",
            },
            {
                "label": "Batches",
                "value": selected_run["batch_count"],
                "note": selected_run["provider"].upper(),
            },
        ]
    )
    st.caption(selected_run["digest_summary"])

    with session_scope() as session:
        repository = _repository_class()(session)
        tabs = st.tabs(["Stored Emails", "Stored Recommendations"])
        with tabs[0]:
            if not hasattr(repository, "list_run_email_details") or not hasattr(
                repository,
                "count_run_email_details",
            ):
                st.info(
                    "Detailed stored-email exploration is unavailable until the app reloads "
                    "the newest repository class."
                )
            else:
                filter_col1, filter_col2, filter_col3 = st.columns(
                    [0.28, 0.28, 0.44],
                    gap="medium",
                )
                with filter_col1:
                    priority_filter = st.selectbox(
                        "Priority filter",
                        ["all", "critical", "high", "medium", "low"],
                        key=f"priority_filter_{selected_run_id}",
                    )
                with filter_col2:
                    category_filter = st.selectbox(
                        "Category filter",
                        [
                            "all",
                            "urgent",
                            "work",
                            "finance",
                            "newsletter",
                            "promo",
                            "spam_like",
                            "personal",
                            "opportunity",
                            "low_priority",
                            "unknown",
                        ],
                        key=f"category_filter_{selected_run_id}",
                    )
                with filter_col3:
                    email_page_size = st.select_slider(
                        "Page size",
                        options=[10, 25, 50, 100],
                        value=25,
                        key=f"email_page_size_{selected_run_id}",
                    )
                total_emails = repository.count_run_email_details(
                    selected_run_id,
                    priority=None if priority_filter == "all" else priority_filter,
                    category=None if category_filter == "all" else category_filter,
                )
                email_page = st.number_input(
                    "Email page",
                    min_value=1,
                    max_value=max(1, ((total_emails - 1) // email_page_size) + 1),
                    value=1,
                    step=1,
                    key=f"email_page_{selected_run_id}",
                )
                email_rows = repository.list_run_email_details(
                    selected_run_id,
                    limit=email_page_size,
                    offset=(int(email_page) - 1) * email_page_size,
                    priority=None if priority_filter == "all" else priority_filter,
                    category=None if category_filter == "all" else category_filter,
                )
                st.caption(f"Showing {len(email_rows)} of {total_emails} stored emails.")
                if email_rows:
                    st.dataframe(email_rows, use_container_width=True, hide_index=True)
                else:
                    st.info("No email records match the current explorer filters.")

        with tabs[1]:
            if not hasattr(repository, "list_run_recommendation_details"):
                st.info(
                    "Detailed stored-recommendation exploration is unavailable until the app "
                    "reloads the newest repository class."
                )
            else:
                rec_filter_col1, rec_filter_col2 = st.columns([0.45, 0.55], gap="medium")
                with rec_filter_col1:
                    status_filter = st.selectbox(
                        "Recommendation status",
                        ["all", "safe", "requires_approval", "blocked"],
                        key=f"status_filter_{selected_run_id}",
                    )
                with rec_filter_col2:
                    rec_page_size = st.select_slider(
                        "Recommendation page size",
                        options=[10, 25, 50, 100],
                        value=25,
                        key=f"rec_page_size_{selected_run_id}",
                    )
                total_recommendations = repository.count_run_recommendations(
                    selected_run_id,
                    status=None if status_filter == "all" else status_filter,
                )
                rec_page = st.number_input(
                    "Recommendation page",
                    min_value=1,
                    max_value=max(1, ((total_recommendations - 1) // rec_page_size) + 1),
                    value=1,
                    step=1,
                    key=f"rec_page_{selected_run_id}",
                )
                recommendation_rows = repository.list_run_recommendation_details(
                    selected_run_id,
                    limit=rec_page_size,
                    offset=(int(rec_page) - 1) * rec_page_size,
                    status=None if status_filter == "all" else status_filter,
                )
                st.caption(
                    "Showing "
                    f"{len(recommendation_rows)} of {total_recommendations} "
                    "stored recommendations."
                )
                if recommendation_rows:
                    st.dataframe(recommendation_rows, use_container_width=True, hide_index=True)
                else:
                    st.info("No recommendation rows match the current explorer filters.")
    card_close()


def _render_control_deck(result: Optional[TriageRunResult]) -> Optional[TriageRunResult]:
    service = _service()
    settings = _workspace_settings(service)
    notice = st.session_state.pop("workspace_notice", None)
    provider_options = _provider_options()
    provider_default = st.session_state.get(
        "workspace_provider",
        getattr(settings, "preferred_provider", provider_options[0]),
    )
    if provider_default not in provider_options:
        provider_default = provider_options[0]
    crew_tone, crew_summary = _crew_status(result)
    st.markdown("### Command Center")
    st.caption(
        "Choose a provider, size the scan window, and keep the workspace responsive even "
        "when you are simulating 10K+ unread emails."
    )
    if notice:
        render_callout(notice["title"], notice["body"], tone=notice["tone"])
    controls_col, stage_col = st.columns([1.2, 0.8], gap="large")
    with controls_col:
        with st.container(border=True):
            playbook_options = _playbook_choices()
            selected_playbook = st.selectbox(
                "Operator playbook",
                playbook_options,
                index=playbook_options.index(st.session_state.get("workspace_playbook", "balanced"))
                if st.session_state.get("workspace_playbook", "balanced") in playbook_options
                else 0,
                format_func=lambda slug: _playbook_definition(slug)["label"],
                key="workspace_playbook",
            )
            playbook = _playbook_definition(selected_playbook)
            render_pill_row([(label, "chip") for label in playbook["pills"]])
            st.caption(playbook["summary"])
            if st.button("Apply playbook to workspace", use_container_width=True):
                _apply_workspace_playbook(service, selected_playbook)
                st.rerun()
            st.markdown("#### Triage Settings")
            st.caption(
                "Start safe, widen the scan only when you need to, and let preview caps keep "
                "the interface fast."
            )
            top_row = st.columns(2, gap="medium")
            with top_row[0]:
                provider = st.selectbox(
                    "Provider",
                    provider_options,
                    index=provider_options.index(provider_default),
                    key="workspace_provider",
                )
            with top_row[1]:
                dry_run = st.toggle(
                    "Dry run",
                    value=st.session_state.get(
                        "workspace_dry_run",
                        getattr(settings, "dry_run_default", True),
                    ),
                    key="workspace_dry_run_toggle",
                )
            second_row = st.columns(2, gap="medium")
            with second_row[0]:
                batch_size = st.select_slider(
                    "Batch size",
                    options=[100, 250, 500, 1000],
                    value=st.session_state.get(
                        "workspace_batch_size",
                        getattr(settings, "default_batch_size", 250),
                    ),
                    key="workspace_batch_size_slider",
                )
            with second_row[1]:
                confidence_threshold = st.slider(
                    "Confidence floor",
                    min_value=0.0,
                    max_value=1.0,
                    value=st.session_state.get(
                        "workspace_confidence_threshold",
                        getattr(settings, "default_confidence_threshold", 0.65),
                    ),
                    step=0.05,
                    key="workspace_confidence_slider",
                )

            bottom_row = st.columns(2, gap="medium")
            with bottom_row[0]:
                limit = st.slider(
                    "Unread scan window",
                    min_value=25,
                    max_value=10000,
                    value=st.session_state.get(
                        "workspace_limit",
                        getattr(settings, "default_scan_limit", 500),
                    ),
                    step=25,
                    key="workspace_limit_slider",
                )
            with bottom_row[1]:
                email_preview_limit = st.slider(
                    "Email preview cap",
                    min_value=25,
                    max_value=500,
                    value=st.session_state.get(
                        "workspace_email_preview_limit",
                        getattr(settings, "default_email_preview_limit", 120),
                    ),
                    step=25,
                    key="workspace_email_preview_slider",
                )
            recommendation_preview_limit = st.slider(
                "Recommendation preview cap",
                min_value=25,
                max_value=1000,
                value=st.session_state.get(
                    "workspace_recommendation_preview_limit",
                    getattr(settings, "default_recommendation_preview_limit", 180),
                ),
                step=25,
                key="workspace_recommendation_preview_slider",
            )

            render_callout(
                "Scale guidance",
                (
                    "For 10K+ inboxes, increase batch size first and let preview caps protect "
                    "the workspace from rendering too much at once."
                ),
                tone="info",
            )

            action_col, policy_col = st.columns(2, gap="medium")
            with action_col:
                run_clicked = st.button(
                    "Run inbox triage",
                    use_container_width=True,
                    type="primary",
                )
            with policy_col:
                with st.popover("Safety policy"):
                    st.markdown(
                        "\n".join(
                            [
                                "- InboxAnchor recommends first and acts second.",
                                (
                                    "- High-priority, finance, personal, and attachment-heavy "
                                    "mail stays gated."
                                ),
                                "- Trash requires a second confirmation at execution time.",
                                "- Full message bodies and secrets should never be logged.",
                            ]
                        )
                    )

    with stage_col:
        profile = _provider_profile(provider if "provider" in locals() else provider_default)
        connection = _provider_connection_state(
            service,
            provider if "provider" in locals() else provider_default,
        )
        with st.container(border=True):
            st.markdown("#### Provider Readiness")
            render_pill_row(
                [
                    (profile.family, "chip"),
                    (profile.auth_mode, "chip"),
                    (
                        "live ready" if profile.live_ready else "setup required",
                        "safe" if profile.live_ready else "review",
                    ),
                    (
                        connection.status.replace("_", " "),
                        "safe" if connection.status == "connected" else "review",
                    ),
                ]
            )
            st.write(profile.best_for)
            if connection.account_hint:
                st.caption(f"Account hint: {connection.account_hint}")
            st.caption("Capabilities: " + " · ".join(profile.capabilities[:3]))
            if profile.safety_notes:
                st.caption(profile.safety_notes[0])
            if profile.slug != "fake":
                render_callout(
                    "Sandbox provider preview",
                    (
                        f"{profile.label} currently runs in a safe preview mode with seeded "
                        "mailbox data while the live connector is being wired. Use it to test "
                        "policy, triage, approvals, and UI flows without touching a real inbox."
                    ),
                    tone="warning",
                )
        render_operator_stage(crew_tone, crew_summary)

    if run_clicked:
        st.session_state.service = _service_class()(provider_name=provider)
        st.session_state.execution_results = []
        st.session_state.workspace_dry_run = dry_run
        st.session_state.workspace_batch_size = batch_size
        st.session_state.workspace_confidence_threshold = confidence_threshold
        st.session_state.workspace_limit = limit
        st.session_state.workspace_email_preview_limit = email_preview_limit
        st.session_state.workspace_recommendation_preview_limit = recommendation_preview_limit
        active_service = st.session_state.service
        with st.spinner("Scanning unread inbox and preparing supervised actions..."):
            st.session_state.result = _run_engine_compat(
                active_service.engine,
                dry_run=dry_run,
                limit=limit,
                batch_size=batch_size,
                confidence_threshold=confidence_threshold,
                email_preview_limit=email_preview_limit,
                recommendation_preview_limit=recommendation_preview_limit,
                workspace_policy=settings.policy,
            )
        st.rerun()

    return st.session_state.get("result")


def main() -> None:
    st.set_page_config(
        page_title="InboxAnchor",
        page_icon="⚓",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_styles()
    if not _render_auth_gate():
        return
    service = _service()
    current_result = st.session_state.get("result")
    _hero(current_result, service)

    flash = st.session_state.pop("execution_flash", None)
    if flash:
        render_callout("Execution completed", flash, tone="success")

    result = _render_control_deck(current_result)
    service = _service()
    runs, audit_entries = _load_dashboard_data()

    _metric_snapshot(result, service)

    if result is None:
        render_empty_state(
            "InboxAnchor is ready for the first triage pass",
            (
                "Start with the fake provider to see the workflow, then move toward Gmail or "
                "IMAP-family providers once you are ready to test live inbox behavior."
            ),
            [
                (
                    "Choose a provider",
                    "Use fake, Gmail, IMAP, Yahoo, or Outlook-oriented flows.",
                ),
                (
                    "Run triage",
                    "Scan unread mail in batches and cap previews for responsiveness.",
                ),
                (
                    "Review safely",
                    "Queue low-risk actions, approve riskier ones, then audit every step.",
                ),
            ],
        )
        st.markdown(
            '<div class="ia-section-note">'
            "Before the first run, set your workspace defaults, tune the cleanup policy, "
            "and mark which provider is only demo-ready versus closer to live usage."
            "</div>",
            unsafe_allow_html=True,
        )
        setup_provider = st.session_state.get(
            "workspace_provider",
            getattr(_workspace_settings(service), "preferred_provider", "fake"),
        )
        preflight_tabs = st.tabs(["Provider Setup", "Workspace Defaults", "Policy Studio"])
        with preflight_tabs[0]:
            _render_provider_profile(setup_provider, service)
            _render_provider_setup_panel(service, setup_provider)
        with preflight_tabs[1]:
            _render_workspace_settings_panel(service)
        with preflight_tabs[2]:
            _render_policy_studio(service)
        return

    operations_tab, studio_tab, history_tab = st.tabs(
        ["Operations", "Workspace Studio", "History & Audit"]
    )

    with operations_tab:
        st.markdown(
            '<div class="ia-section-note">'
            "Read the digest, inspect the priority queue, then move through the action lanes "
            "without losing the audit trail."
            "</div>",
            unsafe_allow_html=True,
        )
        active_settings = _workspace_settings(service)
        overview_col, control_col = st.columns([1.08, 0.92], gap="medium")
        with overview_col:
            _render_inbox_overview(result)
            card_open("Category Map", "How the unread workload breaks down across the current run.")
            _render_category_counts(result)
            card_close()
        with control_col:
            _render_run_health(result, service)
            _render_focus_inbox(result)
            _render_follow_up_radar(result, active_settings)

        content_col, side_col = st.columns([1.12, 0.88], gap="medium")
        with content_col:
            _render_recommendations(result, service)
        with side_col:
            _render_action_items(result)
            _render_suggested_replies(result)
            _render_provider_profile(result.provider, service)

    with studio_tab:
        st.markdown(
            '<div class="ia-section-note">'
            "This is the control plane for how InboxAnchor behaves across future runs: provider "
            "state, workspace defaults, and cleanup policy all live here."
            "</div>",
            unsafe_allow_html=True,
        )
        studio_tabs = st.tabs(["Provider", "Workspace", "Policy"])
        with studio_tabs[0]:
            _render_provider_profile(result.provider, service)
            _render_provider_setup_panel(service, result.provider)
        with studio_tabs[1]:
            _render_workspace_settings_panel(service)
        with studio_tabs[2]:
            _render_policy_studio(service)

    with history_tab:
        st.markdown(
            '<div class="ia-section-note">'
            "Use history and audit data to understand how the inbox changed over time and how "
            "stored runs compare against the current preview."
            "</div>",
            unsafe_allow_html=True,
        )
        history_col, audit_col = st.columns([1.04, 0.96], gap="medium")
        with history_col:
            _render_run_history(runs)
            _render_run_explorer(result, runs)
        with audit_col:
            _render_audit_log(audit_entries)


if __name__ == "__main__":
    main()
