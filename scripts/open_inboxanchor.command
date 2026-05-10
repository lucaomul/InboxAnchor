#!/bin/zsh

set -euo pipefail

BACKEND_URL="http://127.0.0.1:8010/health"
FRONTEND_URL="http://127.0.0.1:8080/login"
FRONTEND_ROOT="/Users/lucaomul/InboxAnchor/frontend"
FRONTEND_LOG="/private/tmp/inboxanchor-frontend.log"
BACKEND_LABEL="gui/$(id -u)/com.luca.inboxanchor.backend"

launchctl kickstart -k "$BACKEND_LABEL" >/dev/null 2>&1 || true

if ! curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
  (
    cd "$FRONTEND_ROOT"
    nohup npm run dev >"$FRONTEND_LOG" 2>&1 &
  )
fi

for _ in {1..30}; do
  if curl -fsS "$BACKEND_URL" >/dev/null 2>&1 && curl -fsS "$FRONTEND_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

osascript <<'APPLESCRIPT'
tell application "Safari"
  activate
  open location "http://127.0.0.1:8080/login"
end tell
APPLESCRIPT
