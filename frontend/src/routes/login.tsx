import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/hooks/use-auth";
import { getApiUrl, setApiUrl } from "@/lib/api-client";
import {
  AlertCircle,
  Anchor,
  ArrowRight,
  CheckCircle2,
  Inbox,
  Mail,
  Server,
  ShieldCheck,
  Sparkles,
  Tags,
} from "lucide-react";

type AuthView = "signin" | "signup" | "gmail";

const WELCOME_POINTS = [
  {
    icon: ShieldCheck,
    title: "Human-approved mailbox actions",
    body: "InboxAnchor recommends first, labels safely, and avoids reckless cleanup behavior.",
  },
  {
    icon: Tags,
    title: "Real mailbox upgrades",
    body: "Unread mail can be labeled and cleaned directly inside Gmail or IMAP-based inboxes.",
  },
  {
    icon: Inbox,
    title: "Unread control without losing trust",
    body: "Triage, reminders, cleanup, and follow-up pressure stay visible instead of hidden.",
  },
];

export const Route = createFileRoute("/login")({
  head: () => ({
    meta: [
      { title: "Welcome — InboxAnchor" },
      {
        name: "description",
        content:
          "Sign in to InboxAnchor to run safe unread scans, mailbox labeling, and human-approved cleanup workflows.",
      },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const { authenticated, loading, login, signIn, signUp, loginRedirect } = useAuth();
  const navigate = useNavigate();

  const [apiUrl, setApiUrlLocal] = useState("");
  const [apiConfigured, setApiConfigured] = useState(false);
  const [apiError, setApiError] = useState("");
  const [authView, setAuthView] = useState<AuthView>("signin");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");
  const [signInForm, setSignInForm] = useState({ email: "", password: "" });
  const [signUpForm, setSignUpForm] = useState({
    fullName: "",
    email: "",
    password: "",
  });

  useEffect(() => {
    const currentApiUrl = getApiUrl();
    setApiUrlLocal(currentApiUrl);
    setApiConfigured(Boolean(currentApiUrl));
  }, []);

  useEffect(() => {
    if (!loading && authenticated) {
      navigate({ to: "/" });
    }
  }, [loading, authenticated, navigate]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (!code) return;
    setAuthView("gmail");
    setAuthLoading(true);
    login(code, state, `${window.location.origin}/login`)
      .then(() => {
        window.history.replaceState({}, "", "/login");
        navigate({ to: "/" });
      })
      .catch((err) => {
        setAuthError(err instanceof Error ? err.message : "Authentication failed");
        setAuthLoading(false);
      });
  }, [login, navigate]);

  const apiReady = apiConfigured && apiUrl.trim().length > 0;

  const handleSaveApi = () => {
    setApiError("");
    try {
      setApiUrl(apiUrl);
      setApiConfigured(true);
    } catch (err) {
      setApiConfigured(false);
      setApiError(err instanceof Error ? err.message : "Invalid API URL");
    }
  };

  const handleSignIn = async () => {
    setAuthError("");
    setAuthLoading(true);
    try {
      await signIn(signInForm.email, signInForm.password);
      navigate({ to: "/" });
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Sign-in failed");
      setAuthLoading(false);
    }
  };

  const handleSignUp = async () => {
    setAuthError("");
    setAuthLoading(true);
    try {
      await signUp(signUpForm.fullName, signUpForm.email, signUpForm.password);
      navigate({ to: "/" });
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Account creation failed");
      setAuthLoading(false);
    }
  };

  const handleGmailLogin = async () => {
    setAuthLoading(true);
    setAuthError("");
    try {
      await loginRedirect();
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Failed to start Gmail sign-in");
      setAuthLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-sm text-muted-foreground animate-pulse">Loading InboxAnchor...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] max-w-7xl items-center">
        <div className="grid w-full gap-6 lg:grid-cols-[1.15fr_0.85fr]">
          <section className="rounded-[28px] border border-border bg-card px-6 py-7 sm:px-8 sm:py-8">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-border bg-background">
                <Anchor className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold tracking-tight text-foreground">InboxAnchor</p>
                <p className="text-xs text-muted-foreground">
                  Safety-first inbox operations for real mailboxes
                </p>
              </div>
            </div>

            <div className="mt-8 max-w-2xl space-y-4">
              <Badge variant="outline" className="gap-1 text-[10px] uppercase tracking-[0.18em]">
                <Sparkles className="h-3 w-3" />
                Welcome
              </Badge>
              <div className="space-y-3">
                <h1 className="text-4xl font-semibold tracking-tight text-foreground sm:text-5xl">
                  Clean the mailbox itself, not just another inbox view.
                </h1>
                <p className="max-w-xl text-sm leading-6 text-muted-foreground sm:text-base">
                  Sign in to run unread scans, generate useful labels, apply safe cleanup actions,
                  and keep a full audit trail across Gmail and IMAP-family inboxes.
                </p>
              </div>
            </div>

            <div className="mt-8 grid gap-3 sm:grid-cols-3">
              <FeatureMetric label="Unread mapped" value="10k+" note="large inbox windows supported" />
              <FeatureMetric label="Safety lanes" value="4" note="safe, review, blocked, follow-up" />
              <FeatureMetric label="Cleanup mode" value="Human-first" note="approval before risky actions" />
            </div>

            <div className="mt-8 grid gap-4 md:grid-cols-3">
              {WELCOME_POINTS.map((point) => (
                <div key={point.title} className="rounded-2xl border border-border bg-background p-4">
                  <point.icon className="h-4 w-4 text-primary" />
                  <h2 className="mt-3 text-sm font-semibold text-foreground">{point.title}</h2>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">{point.body}</p>
                </div>
              ))}
            </div>

            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                to="/"
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
              >
                Explore command center
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                to="/inbox"
                className="inline-flex items-center gap-1.5 rounded-md text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                Open inbox workspace
              </Link>
            </div>
          </section>

          <section className="rounded-[28px] border border-border bg-card p-6 sm:p-7">
            <div className="space-y-5">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-muted-foreground">
                    Account access
                  </p>
                  <h2 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
                    Sign in to continue
                  </h2>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Use an InboxAnchor account or connect Gmail directly. API setup stays local to
                    this browser.
                  </p>
                </div>
                {apiReady ? (
                  <Badge variant="safe" className="text-[10px]">
                    API ready
                  </Badge>
                ) : (
                  <Badge variant="warning" className="text-[10px]">
                    Configure API
                  </Badge>
                )}
              </div>

              <div className="rounded-2xl border border-border bg-background p-4">
                <div className="flex items-center gap-2">
                  <Server className="h-4 w-4 text-primary" />
                  <h3 className="text-sm font-semibold text-foreground">Backend connection</h3>
                </div>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  Set the base URL of the InboxAnchor backend you want this frontend to use.
                </p>
                <div className="mt-3 flex gap-2">
                  <Input
                    value={apiUrl}
                    onChange={(event) => setApiUrlLocal(event.target.value)}
                    placeholder="http://127.0.0.1:8000"
                    className="flex-1"
                  />
                  <Button onClick={handleSaveApi} variant="outline">
                    Save
                  </Button>
                </div>
                <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
                  Local testing works best with <span className="font-medium text-foreground">http://127.0.0.1:8000</span>.
                  If you use <span className="font-medium text-foreground">localhost</span>, some browsers may fail to
                  reach a backend that is only listening on IPv4.
                </p>
                {apiError && (
                  <p className="mt-2 flex items-center gap-1 text-xs text-destructive">
                    <AlertCircle className="h-3.5 w-3.5" />
                    {apiError}
                  </p>
                )}
              </div>

              <div className="grid grid-cols-3 gap-2 rounded-2xl border border-border bg-background p-1.5">
                {(["signin", "signup", "gmail"] as AuthView[]).map((candidate) => (
                  <button
                    key={candidate}
                    onClick={() => {
                      setAuthError("");
                      setAuthView(candidate);
                    }}
                    className={`rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
                      authView === candidate
                        ? "bg-card text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {candidate === "signin"
                      ? "Sign In"
                      : candidate === "signup"
                        ? "Create Account"
                        : "Gmail"}
                  </button>
                ))}
              </div>

              {authError && (
                <div className="rounded-2xl border border-destructive/25 bg-destructive/10 p-3">
                  <p className="flex items-start gap-2 text-sm text-destructive">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{authError}</span>
                  </p>
                </div>
              )}

              {authView === "signin" && (
                <div className="space-y-4 rounded-2xl border border-border bg-background p-4">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">Welcome back</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Sign in to reopen your workspace, reminders, and provider settings.
                    </p>
                  </div>
                  <div className="space-y-3">
                    <Input
                      type="email"
                      value={signInForm.email}
                      onChange={(event) =>
                        setSignInForm((current) => ({ ...current, email: event.target.value }))
                      }
                      placeholder="you@company.com"
                    />
                    <Input
                      type="password"
                      value={signInForm.password}
                      onChange={(event) =>
                        setSignInForm((current) => ({ ...current, password: event.target.value }))
                      }
                      placeholder="Your password"
                    />
                  </div>
                  <Button
                    onClick={handleSignIn}
                    disabled={authLoading || !apiReady}
                    className="w-full"
                  >
                    {authLoading ? "Signing in..." : "Sign In"}
                  </Button>
                </div>
              )}

              {authView === "signup" && (
                <div className="space-y-4 rounded-2xl border border-border bg-background p-4">
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">Create an account</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Start with a local InboxAnchor account, then connect Gmail or IMAP later.
                    </p>
                  </div>
                  <div className="space-y-3">
                    <Input
                      value={signUpForm.fullName}
                      onChange={(event) =>
                        setSignUpForm((current) => ({ ...current, fullName: event.target.value }))
                      }
                      placeholder="Full name"
                    />
                    <Input
                      type="email"
                      value={signUpForm.email}
                      onChange={(event) =>
                        setSignUpForm((current) => ({ ...current, email: event.target.value }))
                      }
                      placeholder="you@company.com"
                    />
                    <Input
                      type="password"
                      value={signUpForm.password}
                      onChange={(event) =>
                        setSignUpForm((current) => ({ ...current, password: event.target.value }))
                      }
                      placeholder="Create a password"
                    />
                  </div>
                  <Button
                    onClick={handleSignUp}
                    disabled={authLoading || !apiReady}
                    className="w-full"
                  >
                    {authLoading ? "Creating account..." : "Create Account"}
                  </Button>
                </div>
              )}

              {authView === "gmail" && (
                <div className="space-y-4 rounded-2xl border border-border bg-background p-4">
                  <div className="flex items-center gap-2">
                    <Mail className="h-4 w-4 text-primary" />
                    <div>
                      <h3 className="text-sm font-semibold text-foreground">Connect with Gmail</h3>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Use Google OAuth to connect a live mailbox and bring Gmail directly into the
                        InboxAnchor workflow.
                      </p>
                    </div>
                  </div>
                  <div className="rounded-2xl border border-border bg-card p-3">
                    <p className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
                      InboxAnchor reads unread state, applies useful labels, and never trashes mail
                      without explicit confirmation.
                    </p>
                  </div>
                  <div className="rounded-2xl border border-border bg-card p-3">
                    <p className="text-xs leading-5 text-muted-foreground">
                      Before connecting Gmail, make sure the backend has
                      <span className="mx-1 font-medium text-foreground">GMAIL_CREDENTIALS_PATH</span>
                      configured and that Google OAuth allows this frontend login URL as a redirect.
                    </p>
                  </div>
                  <Button
                    onClick={handleGmailLogin}
                    disabled={authLoading || !apiReady}
                    className="w-full"
                  >
                    {authLoading ? "Redirecting to Google..." : "Continue with Gmail"}
                  </Button>
                </div>
              )}

              {!apiReady && (
                <p className="text-xs text-warning">
                  Save an API URL first to unlock account sign-in, account creation, and Gmail
                  connection.
                </p>
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function FeatureMetric({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: string;
}) {
  return (
    <div className="rounded-2xl border border-border bg-background p-4">
      <p className="text-2xl font-semibold tracking-tight text-foreground">{value}</p>
      <p className="mt-1 text-sm font-medium text-foreground">{label}</p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">{note}</p>
    </div>
  );
}
