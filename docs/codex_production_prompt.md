# InboxAnchor Productionization Prompt

Use this prompt when you want Codex to continue the productionization of InboxAnchor without fighting the current architecture.

```text
You are a senior Python backend engineer helping me productionize InboxAnchor.

Repository:
https://github.com/lucaomul/InboxAnchor

Project summary:
InboxAnchor is a safety-first inbox operations system for overloaded inboxes. It classifies, prioritizes, summarizes, extracts actions, drafts replies, recommends cleanup, requires human approval for risky actions, and writes a full audit trail. It already includes:

- specialized agents
- rules engine
- triage engine
- FastAPI backend
- Streamlit dashboard
- SQLAlchemy persistence
- fake/demo provider flows
- offline tests

Primary goal:
Add production-ready transport, resilience, and scale features without changing the existing product philosophy or core workflow.

Non-negotiable rules:
- Preserve the existing triage engine contract and approval workflow.
- Keep `dry_run=True` as the default for destructive operations.
- Never log email body contents, secrets, OAuth tokens, or credentials.
- Prefer minimal targeted changes over introducing a parallel architecture.
- Update tests, docs, settings, and dependency files when necessary.
- If optional dependencies are missing, fail gracefully with clear messages instead of crashing imports.

Current architecture constraints:
- `GmailClient` is an email provider façade with a pluggable `GmailTransport` protocol.
- `IMAPEmailClient` is currently the preview/demo IMAP-family provider.
- `InboxAnchorService` is the boot path for provider selection and engine creation.
- The API currently lives in `inboxanchor/api/main.py`; do not assume a larger router architecture unless you add it minimally and cleanly.
- The dashboard and API should remain usable in preview mode when live providers are not configured.

Implementation priorities:

1. Gmail production path
- Add a real Gmail transport behind the existing `GmailTransport` protocol.
- Use OAuth credentials and token files from external paths or environment variables.
- Support unread listing, paging, body extraction, labels, archive, trash, and read-state updates.
- Add Gmail setup docs.

2. IMAP production path
- Add a real IMAP transport for generic IMAP, Yahoo, and Outlook-style inboxes.
- Use UID operations, MIME parsing, archive/trash folder moves, and safe fallbacks.
- Keep the existing preview provider path for demos.

3. Resilience
- Add retry and timeout handling for LLM provider calls.
- Convert provider failures into structured non-fatal results.
- Never let one failed model call crash a triage run.

4. Incremental scale
- Add checkpoint persistence.
- Wrap the existing triage engine with an incremental engine instead of rewriting it.
- Use provider-specific incremental paths when available, otherwise fall back to full scan.

5. Optional push/webhook path
- Add Gmail watch/webhook support only as an optional enhancement.
- Keep imports lazy and the API stable if Pub/Sub dependencies are missing.

When making changes:
- Inspect the repo first.
- Reuse existing abstractions.
- Add tests for each new production seam.
- Update README/docs if user-facing behavior changes.

Deliverables:
- code changes
- tests
- docs
- a short summary of:
  - files changed
  - safety implications
  - configuration required
  - current limitations
```
