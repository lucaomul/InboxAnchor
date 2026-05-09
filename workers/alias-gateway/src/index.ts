interface Env {
  INBOXANCHOR_BASE_URL: string;
  INBOXANCHOR_ALIAS_RESOLVER_SECRET: string;
}

interface AliasResolveResponse {
  active: boolean;
  action: "forward" | "reject";
  reason?: string;
  alias_address?: string;
  forward_to?: string;
  owner_email?: string;
  label_name?: string;
  purpose?: string;
  alias_type?: string;
  provider?: string;
  skip_inbox?: boolean;
}

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

async function resolveAlias(
  message: ForwardableEmailMessage,
  env: Env,
): Promise<AliasResolveResponse> {
  const response = await fetch(`${normalizeBaseUrl(env.INBOXANCHOR_BASE_URL)}/aliases/resolve`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-InboxAnchor-Alias-Secret": env.INBOXANCHOR_ALIAS_RESOLVER_SECRET,
    },
    body: JSON.stringify({
      alias_address: message.to,
      sender: message.from,
      subject: message.headers.get("subject") || "",
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Alias resolver failed with ${response.status}: ${body}`);
  }

  return (await response.json()) as AliasResolveResponse;
}

export default {
  async email(message: ForwardableEmailMessage, env: Env): Promise<void> {
    const resolved = await resolveAlias(message, env);

    if (!resolved.active || resolved.action !== "forward" || !resolved.forward_to) {
      message.setReject(resolved.reason || "Alias is inactive.");
      return;
    }

    const customHeaders = new Headers();
    customHeaders.set("X-InboxAnchor-Alias", resolved.alias_address || message.to);
    customHeaders.set("X-InboxAnchor-Alias-Label", resolved.label_name || "InboxAnchor/Aliases");
    customHeaders.set("X-InboxAnchor-Alias-Owner", resolved.owner_email || "");
    customHeaders.set("X-InboxAnchor-Original-Recipient", message.to);

    await message.forward(resolved.forward_to, customHeaders);
  },
} satisfies ExportedHandler<Env>;
