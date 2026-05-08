# Gmail OAuth Setup

This project uses a standard Google OAuth desktop flow for live Gmail access.

## 1. Create a Google Cloud project

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project or choose an existing one.

## 2. Enable the Gmail API

1. In the selected project, open **APIs & Services**.
2. Enable **Gmail API**.

## 3. Create OAuth 2.0 credentials

1. Open **Google Auth Platform** or **APIs & Services > Credentials**.
2. Configure the OAuth consent screen if this is the first OAuth client in the project.
3. Create a new **OAuth client ID**.
4. Choose **Desktop app** as the application type.
5. Download the client secrets JSON file.

## 4. Save `credentials.json`

Store the downloaded file outside the repo or in a private local app-data path.

Example:

```bash
mkdir -p ~/.config/inboxanchor
mv ~/Downloads/client_secret_*.json ~/.config/inboxanchor/credentials.json
```

## 5. Run the OAuth flow once

The first run opens a browser for consent and creates `token.json`.

Example:

```python
from inboxanchor.connectors.oauth_flow import get_credentials

get_credentials(
    credentials_path="/Users/you/.config/inboxanchor/credentials.json",
    token_path="/Users/you/.config/inboxanchor/token.json",
    scopes=["https://www.googleapis.com/auth/gmail.modify"],
)
```

On later runs, the token is refreshed silently when possible.

## 6. Required scope

InboxAnchor uses:

- `https://www.googleapis.com/auth/gmail.modify`

This scope is required because the app reads messages, applies labels, removes inbox state, marks messages as read, and moves messages to trash when the human approval flow allows it.

## 7. Environment variables

Set the credential paths in your local environment:

```bash
export GMAIL_CREDENTIALS_PATH="/Users/you/.config/inboxanchor/credentials.json"
export GMAIL_TOKEN_PATH="/Users/you/.config/inboxanchor/token.json"
```

## 8. Wiring the live transport

Minimal code example:

```python
from inboxanchor.connectors.gmail_client import GmailClient
from inboxanchor.connectors.gmail_transport import GoogleAPITransport

client = GmailClient(
    transport=GoogleAPITransport(
        credentials_path="/Users/you/.config/inboxanchor/credentials.json",
        token_path="/Users/you/.config/inboxanchor/token.json",
    )
)
```

## 9. Security reminder

- `credentials.json` and `token.json` must stay out of version control.
- They should live in private local paths or injected runtime mounts.
- The repo `.gitignore` already excludes `.env`, `*.db`, and other local artifacts. Keep OAuth credential files outside the repo whenever possible.
