# InboxAnchor Auth + README Alignment Prompt

You are an expert Python product engineer helping me refine InboxAnchor without fighting the current codebase.

## Repository Context

InboxAnchor already includes:

- a full triage engine with Classifier, Priority, Summarizer, ActionExtractor, ReplyDrafter, and SafetyVerifier
- OpenAI and Groq-backed LLM integration with heuristic fallback
- Gmail OAuth transport and IMAP transport support
- FastAPI routes for auth, triage, actions, audit, OAuth, provider settings, and webhooks
- SQLAlchemy persistence, auth sessions, audit logging, retries, and incremental triage
- a Streamlit dashboard with a real auth gate and account-aware workspace flow

Repository:
`https://github.com/lucaomul/InboxAnchor`

## Important Current-State Rules

Before making changes, inspect the repo and preserve what already exists.

Do not:

- add a second auth system
- re-implement the auth API
- replace the existing triage flow
- rewrite connector, infra, or core architecture unless a minimal targeted fix is required

The dashboard already has:

- `_current_account_user()`
- `_login_account()`
- `_signup_account()`
- `_logout_account()`
- `_render_auth_gate()`

Preserve those functions unless a small targeted improvement is necessary.

## Goal

Improve the current auth UX and rewrite the README so it accurately reflects the real repo.

## Work Order

### 1. Audit the Current Auth UX

Inspect:

- `inboxanchor/app/dashboard.py`
- `inboxanchor/app/ui.py`
- `inboxanchor/infra/auth.py`
- `inboxanchor/api/main.py`

Look for:

- dead or unused auth state keys
- login/sign-up controls that do not influence the rendered auth view
- logout placement that feels bolted on
- auth text, spacing, or state transitions that feel inconsistent with the rest of the product
- places where database/auth failures surface poorly in the dashboard

Important:

- Preserve `st.session_state["auth_token"]`
- Preserve `st.session_state["auth_user"]`
- Never store passwords in session state
- Do not remove demo access unless explicitly asked

### 2. Improve the Auth Surface Without Restructuring the Whole Dashboard

Allowed changes:

- improve `_render_auth_gate()`
- improve login / sign-up / demo view switching
- improve logout presentation inside the existing workspace shell
- improve auth-related copy, spacing, and state handling
- improve graceful error handling around `AuthService` calls inside the dashboard
- improve CSS in `inboxanchor/app/ui.py` if necessary

Do not:

- replace the dashboard architecture
- move auth into a separate frontend framework
- change `AuthService` contracts unless absolutely required

### 3. Rewrite README.md to Match the Real Repo

The README must reflect the code that actually exists today.

It should cover:

- what InboxAnchor is
- safety-first design
- actual provider story
- actual LLM provider behavior
- auth model
- dashboard and API surfaces
- setup paths for demo mode, OpenAI/Groq-backed runs, Gmail, and IMAP
- real endpoint list from `inboxanchor/api/main.py`
- current roadmap and current limitations

Important:

- do not invent endpoints
- do not document `/api/v1/...` routes unless they really exist at runtime
- do not say the dashboard lacks auth
- do not say Gmail transport is missing if it already exists
- be explicit about what is demo-safe vs live-configurable

## Delivery Requirements

When editing:

- prefer minimal targeted changes
- keep all existing tests passing
- add tests only if needed for newly fixed behavior
- show diffs or changed sections when useful

## Suggested Validation

Run:

```bash
python -m ruff check .
python -m pytest tests --tb=short
```

If UI/auth changes are made, validate the auth screen manually in Streamlit too.
