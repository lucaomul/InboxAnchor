# Gmail Push Notifications Setup

## What this enables
New Gmail mail can trigger incremental InboxAnchor triage automatically in a few seconds. No manual refresh is required after the watch is active.

## Prerequisites
- A Google Cloud project with the Pub/Sub API enabled
- The Gmail API enabled on the same project
- An InboxAnchor backend reachable on a public HTTPS URL

## Step 1 — Create the Pub/Sub topic
```bash
gcloud pubsub topics create inboxanchor-gmail-push
```

## Step 2 — Grant Gmail permission to publish
```bash
gcloud pubsub topics add-iam-policy-binding inboxanchor-gmail-push \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

## Step 3 — Create a push subscription to InboxAnchor
```bash
gcloud pubsub subscriptions create inboxanchor-gmail-sub \
  --topic=inboxanchor-gmail-push \
  --push-endpoint=https://YOUR_DOMAIN/api/v1/webhooks/gmail \
  --ack-deadline=30
```

## Step 4 — Configure InboxAnchor
Add to your environment:

```bash
GMAIL_PUBSUB_TOPIC=projects/YOUR_PROJECT/topics/inboxanchor-gmail-push
INBOXANCHOR_GMAIL_WATCH_AUTO_RENEW=true
```

## Step 5 — Register the Gmail watch
Call:

```http
POST /api/v1/ops/watch/start
Content-Type: application/json

{
  "topic_name": "projects/YOUR_PROJECT/topics/inboxanchor-gmail-push",
  "label_ids": ["UNREAD"]
}
```

## Step 6 — Verify the webhook surface
Call:

```http
GET /api/v1/health/webhook
```

Expected shape:

```json
{"status":"healthy","connected_clients":0}
```

## Renewal
InboxAnchor renews the Gmail watch every 6 days when `INBOXANCHOR_GMAIL_WATCH_AUTO_RENEW=true`. Gmail watches expire after 7 days, so renewal needs to happen before that deadline.
