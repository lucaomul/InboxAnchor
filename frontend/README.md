# InboxAnchor Frontend

This directory contains the TanStack/React product frontend for InboxAnchor. It began as an import from the separate `lucaomul/inbox-assistant` repository and is now adapted to the current InboxAnchor FastAPI backend.

## What Is Here

- React 19 + TanStack Router application
- Tailwind 4 / Radix UI product shell
- mailbox command center, inbox workspace, welcome/login flow, and settings routes
- mock-data and API client layers used by the frontend app

## Run Locally

```bash
npm install
npm run dev
```

## Current Status

- the frontend source is now part of the main InboxAnchor repository
- the React app is wired to the current FastAPI backend for auth, command-center workflows, mailbox operations, and inbox views
- the Streamlit workspace remains available alongside it for Python-native operations, admin flows, and debugging

## Source

- repository: `https://github.com/lucaomul/inbox-assistant`
- imported snapshot: `main` branch clone used on May 8, 2026
