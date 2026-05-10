# InboxAnchor Alias Gateway

This Cloudflare Email Worker is the managed-domain bridge for product-owned aliases such as
`travel1234567@inboxanchor.com`.

## What it does

1. Receives inbound email for the alias domain in Cloudflare Email Routing.
2. Calls the InboxAnchor backend at `POST /aliases/resolve`.
3. If the alias is active, forwards the message to the resolved destination inbox.
4. If the alias is revoked or unknown, rejects the message.

The Worker adds these forwarding headers:

- `X-InboxAnchor-Alias`
- `X-InboxAnchor-Alias-Label`
- `X-InboxAnchor-Alias-Owner`
- `X-InboxAnchor-Original-Recipient`

## Required backend env

Set this on the InboxAnchor API:

```bash
INBOXANCHOR_ALIAS_MANAGED_ENABLED=true
INBOXANCHOR_ALIAS_DOMAIN=inboxanchor.com
INBOXANCHOR_ALIAS_RESOLVER_SECRET=replace-with-a-long-random-secret
INBOXANCHOR_ALIAS_RESOLVER_BASE_URL=https://your-public-inboxanchor-api.example.com
INBOXANCHOR_ALIAS_INBOUND_READY=true
```

## Required Worker vars

Set these in `wrangler.jsonc` or `wrangler secret put`:

```bash
INBOXANCHOR_BASE_URL=https://your-inboxanchor-api.example.com
INBOXANCHOR_ALIAS_RESOLVER_SECRET=replace-with-the-same-random-secret
```

## Cloudflare routing setup

1. Enable Cloudflare Email Routing for your alias domain.
2. Create a routing rule that sends mail for the alias address or alias pattern to this Worker.
3. Make sure the forward destination used by InboxAnchor is verified in Cloudflare if Cloudflare
   requires destination verification for your account setup.

## Notes

- This is the app-side and Worker-side scaffold.
- The Worker must call a public HTTPS InboxAnchor API. A backend running only on
  `127.0.0.1` or `localhost` cannot resolve aliases for Cloudflare.
- Real `@inboxanchor.com` delivery still requires domain ownership, MX setup, and live Cloudflare
  Email Routing configuration.
