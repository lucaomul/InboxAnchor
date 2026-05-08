import { createFileRoute } from "@tanstack/react-router";
import { InboxWorkspace } from "@/components/inbox/InboxWorkspace";

export const Route = createFileRoute("/inbox")({
  head: () => ({
    meta: [
      { title: "Inbox Workspace — InboxAnchor" },
      {
        name: "description",
        content: "Review unread mail, safety lanes, and suggested actions inside InboxAnchor.",
      },
    ],
  }),
  component: InboxWorkspace,
});
