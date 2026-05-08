# Gmail OAuth Setup

This project supports two local Gmail OAuth patterns:

- the Python helper flow that stores `token.json` locally
- the React frontend flow that redirects back to the frontend login page and exchanges the code through the FastAPI backend

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
4. If you plan to use the Python helper flow directly, choose **Desktop app**.
5. If you plan to connect Gmail from the React frontend, choose **Web application** and add your frontend login URL as an authorized redirect URI.
6. Download the client secrets JSON file.

Typical local frontend redirect URIs:

- `http://127.0.0.1:4173/login`
- `http://localhost:4173/login`
- `http://127.0.0.1:5173/login`
- `http://localhost:5173/login`

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

If you are using the React frontend instead of the Python helper, InboxAnchor will redirect back to the frontend login page and exchange the code through the backend automatically.

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
