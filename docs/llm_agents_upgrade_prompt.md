# InboxAnchor LLM Agent Upgrade Prompt

You are a senior Python engineer working in the InboxAnchor repository.

## Goal

Upgrade InboxAnchor's core AI agent layer from heuristic-only behavior to a safe hybrid design:

- real LLM-backed classification, extraction, drafting, and summarization
- heuristic fast paths for obviously safe or obvious cases
- silent fallback to heuristics when the LLM path fails
- no changes to the triage engine contract or approval workflow

## Important Repository Constraints

Preserve the existing architecture. Prefer minimal, targeted changes.

You may update:

- `inboxanchor/agents/*.py`
- `inboxanchor/infra/llm_providers.py` (new)
- `inboxanchor/config/settings.py`
- `inboxanchor/connectors/oauth_flow.py`
- `inboxanchor/api/v1/routers/oauth.py` (new)
- `inboxanchor/api/main.py`
- `.env.example`
- `pyproject.toml`
- tests

Do not rewrite:

- `inboxanchor/core/triage_engine.py`
- `inboxanchor/agents/safety_verifier.py`
- `inboxanchor/core/rules.py`
- transport/provider contracts
- persistence or retry architecture

## Design Rules

1. `LLMClient` already owns retries, timeouts, and graceful structured failure. Keep that.
2. Provider backends should raise retryable exceptions on transient failures so the current retry layer still works.
3. All four agents must continue to work without API keys by falling back to heuristics.
4. Never log email body content, OAuth codes, or tokens.
5. All tests must remain offline and deterministic.

## Required Changes

### 1. Real provider backends

Create `inboxanchor/infra/llm_providers.py` with:

- `OpenAIBackend`
- `GroqBackend`
- optional `FallbackBackend`
- `build_llm_client()`

Behavior:

- select provider from `INBOXANCHOR_LLM_PROVIDER`
- support OpenAI primary with Groq fallback when both are configured
- support Groq primary with OpenAI fallback when both are configured
- fall back to mock safely if keys or optional SDKs are missing

### 2. Settings / env

Add:

- `OPENAI_API_KEY`
- `GROQ_API_KEY`
- `INBOXANCHOR_OPENAI_MODEL`
- `INBOXANCHOR_GROQ_MODEL`

### 3. Agent upgrades

Upgrade:

- `classifier.py`
- `action_extractor.py`
- `reply_drafter.py`
- `summarizer.py`

Behavior:

- keep heuristics as fast fallback
- use LLM when the heuristic is uncertain
- parse strict JSON for classifier / extractor / summarizer
- keep reply drafts short and professional

### 4. Gmail OAuth web callback

Add:

- `inboxanchor/api/v1/routers/oauth.py`

Wire:

- `GET /oauth/gmail/start`
- `GET /oauth/gmail/callback`

Keep the current installed-app helper working, but add web OAuth helpers so the API route can complete the flow cleanly.

### 5. Tests

Add offline tests for:

- provider backends
- classifier LLM path + fallback
- extractor LLM path + fallback
- reply drafter LLM path + fallback
- summarizer LLM path + fallback
- Gmail OAuth start/callback route behavior

## Delivery Standard

- Keep code readable and modular.
- Avoid introducing a parallel architecture.
- Run `ruff check .` and `pytest tests --tb=short`.
- If something must differ from the original prompt for repo-safety, prefer the existing repo contract over the original prompt wording.
