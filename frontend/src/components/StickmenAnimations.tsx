import {
  StickmanInboxRunner,
  type StickmanInboxRunnerProps,
} from "@/components/StickmanInboxRunner";
import { useLoaderMode } from "@/hooks/use-loader-mode";

type LoaderStat = {
  label: string;
  value: string | number;
};

// Animated stickmen SVG characters for loading states and visual accents

function WalkCycle({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 80 100" className={`w-16 h-20 ${className}`} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      {/* Head */}
      <circle cx="40" cy="18" r="10" className="animate-[bounce_2s_ease-in-out_infinite]" />
      {/* Body */}
      <line x1="40" y1="28" x2="40" y2="58" />
      {/* Arms waving */}
      <g className="origin-[40px_38px]" style={{ animation: "sway 1s ease-in-out infinite alternate" }}>
        <line x1="40" y1="38" x2="20" y2="48" />
        <line x1="40" y1="38" x2="60" y2="48" />
      </g>
      {/* Legs walking */}
      <g style={{ animation: "walk 0.6s ease-in-out infinite alternate" }}>
        <line x1="40" y1="58" x2="28" y2="85" />
        <line x1="40" y1="58" x2="52" y2="85" />
      </g>
      {/* Eyes — dots */}
      <circle cx="36" cy="16" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="44" cy="16" r="1.5" fill="currentColor" stroke="none" />
      {/* Smile */}
      <path d="M36 22 Q40 26 44 22" fill="none" />
    </svg>
  );
}

function MailCarrier({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={`w-20 h-20 ${className}`} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      {/* Head */}
      <circle cx="50" cy="18" r="10" />
      <circle cx="46" cy="16" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="54" cy="16" r="1.5" fill="currentColor" stroke="none" />
      <path d="M46 22 Q50 25 54 22" fill="none" />
      {/* Body */}
      <line x1="50" y1="28" x2="50" y2="58" />
      {/* Left arm holding envelope */}
      <line x1="50" y1="38" x2="30" y2="45" />
      {/* Envelope bouncing */}
      <g style={{ animation: "float 1.5s ease-in-out infinite" }}>
        <rect x="15" y="38" width="18" height="12" rx="1.5" className="fill-primary/20 stroke-primary" />
        <path d="M15 38 L24 46 L33 38" className="stroke-primary" fill="none" />
      </g>
      {/* Right arm waving */}
      <g style={{ animation: "wave 0.8s ease-in-out infinite alternate" }}>
        <line x1="50" y1="38" x2="72" y2="30" />
        <line x1="72" y1="30" x2="78" y2="22" />
      </g>
      {/* Legs */}
      <line x1="50" y1="58" x2="38" y2="85" />
      <line x1="50" y1="58" x2="62" y2="85" />
    </svg>
  );
}

function Thinking({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 80 110" className={`w-16 h-22 ${className}`} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      {/* Head */}
      <circle cx="40" cy="20" r="10" />
      {/* Eyes looking up */}
      <circle cx="36" cy="17" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="44" cy="17" r="1.5" fill="currentColor" stroke="none" />
      {/* Thinking mouth */}
      <line x1="37" y1="24" x2="43" y2="24" />
      {/* Body */}
      <line x1="40" y1="30" x2="40" y2="60" />
      {/* Left arm — hand on chin */}
      <line x1="40" y1="40" x2="25" y2="35" />
      <line x1="25" y1="35" x2="32" y2="26" />
      {/* Right arm relaxed */}
      <line x1="40" y1="40" x2="58" y2="52" />
      {/* Legs crossed */}
      <line x1="40" y1="60" x2="30" y2="88" />
      <line x1="40" y1="60" x2="50" y2="88" />
      {/* Thought bubbles */}
      <g style={{ animation: "float 2s ease-in-out infinite" }}>
        <circle cx="55" cy="8" r="2" className="fill-primary/30" stroke="none" />
        <circle cx="60" cy="2" r="3" className="fill-primary/20" stroke="none" />
        <circle cx="68" cy="-5" r="4" className="fill-primary/10" stroke="none" />
      </g>
    </svg>
  );
}

function Celebrating({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 80 100" className={`w-16 h-20 ${className}`} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      {/* Head */}
      <circle cx="40" cy="20" r="10" style={{ animation: "bounce 1s ease-in-out infinite" }} />
      {/* Happy eyes */}
      <path d="M34 17 Q36 14 38 17" fill="none" />
      <path d="M42 17 Q44 14 46 17" fill="none" />
      {/* Big smile */}
      <path d="M34 23 Q40 30 46 23" fill="none" />
      {/* Body */}
      <line x1="40" y1="30" x2="40" y2="58" />
      {/* Arms up — celebrating */}
      <g style={{ animation: "celebrate 0.5s ease-in-out infinite alternate" }}>
        <line x1="40" y1="38" x2="18" y2="22" />
        <line x1="40" y1="38" x2="62" y2="22" />
        {/* Stars */}
        <circle cx="14" cy="18" r="2" className="fill-warning stroke-warning" style={{ animation: "pulse 1s infinite" }} />
        <circle cx="66" cy="18" r="2" className="fill-warning stroke-warning" style={{ animation: "pulse 1s infinite 0.3s" }} />
      </g>
      {/* Legs */}
      <line x1="40" y1="58" x2="30" y2="85" />
      <line x1="40" y1="58" x2="50" y2="85" />
    </svg>
  );
}

// Loading screen with mail carrier stickman
export function StickmanLoader({
  message = "Loading your inbox...",
  playful = false,
  stage,
  activity,
  stats = [],
  modeOverride,
  runnerProps,
  showModeToggle = true,
}: {
  message?: string;
  playful?: boolean;
  stage?: string;
  activity?: string;
  stats?: LoaderStat[];
  modeOverride?: "fun" | "serious";
  runnerProps?: StickmanInboxRunnerProps;
  showModeToggle?: boolean;
}) {
  const { mode, setMode, isFunMode } = useLoaderMode();
  const resolvedMode = modeOverride ?? mode;
  const resolvedFunMode = modeOverride ? modeOverride === "fun" : isFunMode;

  if (playful) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-6 text-muted-foreground">
        {showModeToggle ? (
          <div className="flex items-center gap-2 rounded-full border border-border bg-card/70 p-1">
            <button
              type="button"
              onClick={() => setMode("fun")}
              className={`rounded-full px-3 py-1 text-[10px] font-medium uppercase tracking-[0.18em] transition-colors ${
                resolvedMode === "fun"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              }`}
            >
              Fun Mode
            </button>
            <button
              type="button"
              onClick={() => setMode("serious")}
              className={`rounded-full px-3 py-1 text-[10px] font-medium uppercase tracking-[0.18em] transition-colors ${
                resolvedMode === "serious"
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-foreground"
              }`}
            >
              Serious Mode
            </button>
          </div>
        ) : null}
        {resolvedFunMode ? (
          <StickmanInboxRunner autoplay {...runnerProps} />
        ) : (
          <div className="flex w-full max-w-[360px] flex-col items-center gap-4 rounded-2xl border border-border bg-background/80 p-6 shadow-sm">
            <div className="h-12 w-12 animate-spin rounded-full border-4 border-border border-t-primary" />
            <div className="space-y-1 text-center">
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                Serious loading
              </p>
              <p className="text-sm text-foreground">
                InboxAnchor is reading and triaging the mailbox.
              </p>
            </div>
          </div>
        )}
        <div className="max-w-lg space-y-3 text-center">
          {stage ? (
            <p className="text-[11px] uppercase tracking-[0.18em] text-primary/80">{stage}</p>
          ) : null}
          <p className="text-sm leading-6 text-muted-foreground">{message}</p>
          {activity ? (
            <p className="text-xs leading-5 text-foreground/80">{activity}</p>
          ) : null}
          {stats.length > 0 ? (
            <div className="grid grid-cols-2 gap-2 text-left sm:grid-cols-4">
              {stats.map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-xl border border-border bg-card/70 px-3 py-2"
                >
                  <p className="text-lg font-semibold text-foreground">{stat.value}</p>
                  <p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                    {stat.label}
                  </p>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center gap-4 py-12 text-muted-foreground">
      <MailCarrier className="text-primary" />
      <p className="text-sm animate-pulse">{message}</p>
    </div>
  );
}

// Empty state with thinking stickman
export function StickmanEmpty({ message = "Nothing here yet" }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-12 text-muted-foreground">
      <Thinking className="text-muted-foreground" />
      <p className="text-sm">{message}</p>
    </div>
  );
}

// Success state with celebrating stickman
export function StickmanSuccess({ message = "All done!" }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-8 text-muted-foreground">
      <Celebrating className="text-safe" />
      <p className="text-sm text-safe">{message}</p>
    </div>
  );
}

// Walking stickman for inline loading
export function StickmanWalking({ className = "" }: { className?: string }) {
  return <WalkCycle className={`text-primary ${className}`} />;
}

// Inline CSS keyframes (injected once)
export function StickmanStyles() {
  return (
    <style>{`
      @keyframes sway {
        0% { transform: rotate(-5deg); }
        100% { transform: rotate(5deg); }
      }
      @keyframes walk {
        0% { transform: skewX(-8deg); }
        100% { transform: skewX(8deg); }
      }
      @keyframes float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-6px); }
      }
      @keyframes wave {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(-15deg); }
      }
      @keyframes celebrate {
        0% { transform: rotate(-3deg); }
        100% { transform: rotate(3deg); }
      }
      @keyframes bounce {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-4px); }
      }
    `}</style>
  );
}
