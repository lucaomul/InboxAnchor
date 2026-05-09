import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

type ObstacleKind = "envelope" | "thread";

type Obstacle = {
  id: number;
  kind: ObstacleKind;
  x: number;
};

type RunnerState = {
  y: number;
  velocityY: number;
  crouching: boolean;
  score: number;
  best: number;
  crashes: number;
  obstacles: Obstacle[];
};

export type StickmanInboxRunnerProps = {
  autoplay?: boolean;
  className?: string;
  showControlsHint?: boolean;
};

const WIDTH = 320;
const HEIGHT = 152;
const GROUND_Y = 116;
const PLAYER_X = 52;
const PLAYER_WIDTH = 24;
const STANDING_HEIGHT = 46;
const CROUCH_HEIGHT = 28;
const ENVELOPE_WIDTH = 28;
const ENVELOPE_HEIGHT = 24;
const THREAD_WIDTH = 34;
const THREAD_TOP = GROUND_Y - 56;
const THREAD_HEIGHT = 20;

function initialState(best = 0, crashes = 0): RunnerState {
  return {
    y: 0,
    velocityY: 0,
    crouching: false,
    score: 0,
    best,
    crashes,
    obstacles: [],
  };
}

function obstacleBox(obstacle: Obstacle) {
  if (obstacle.kind === "envelope") {
    return {
      left: obstacle.x,
      right: obstacle.x + ENVELOPE_WIDTH,
      top: GROUND_Y - ENVELOPE_HEIGHT,
      bottom: GROUND_Y,
    };
  }
  return {
    left: obstacle.x,
    right: obstacle.x + THREAD_WIDTH,
    top: THREAD_TOP,
    bottom: THREAD_TOP + THREAD_HEIGHT,
  };
}

function intersects(a: { left: number; right: number; top: number; bottom: number }, b: { left: number; right: number; top: number; bottom: number }) {
  return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
}

export function StickmanInboxRunner({
  autoplay = false,
  className = "",
  showControlsHint = true,
}: StickmanInboxRunnerProps) {
  const [game, setGame] = useState<RunnerState>(() => initialState());
  const containerRef = useRef<HTMLDivElement | null>(null);
  const jumpQueuedRef = useRef(0);
  const crouchActiveRef = useRef(false);
  const obstacleIdRef = useRef(0);
  const autoplayPatternRef = useRef<ObstacleKind[]>(["envelope", "thread", "envelope", "thread"]);
  const autoplayPatternIndexRef = useRef(0);
  const spawnCooldownRef = useRef(autoplay ? 460 : 900);
  const spawnElapsedRef = useRef(0);

  useEffect(() => {
    containerRef.current?.focus();
  }, []);

  useEffect(() => {
    spawnCooldownRef.current = autoplay ? 460 : 900;
    spawnElapsedRef.current = 0;
    autoplayPatternIndexRef.current = 0;
  }, [autoplay]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent | ReactKeyboardEvent<HTMLDivElement>) => {
      if (["ArrowUp", "ArrowDown", "Space", "KeyW", "KeyS"].includes(event.code)) {
        event.preventDefault();
      }
      if (event.code === "ArrowUp" || event.code === "Space" || event.code === "KeyW") {
        if (!event.repeat) {
          jumpQueuedRef.current += 1;
          setGame((previous) => {
            if (previous.y > 0.001) {
              return previous;
            }
            return {
              ...previous,
              velocityY: 11.2,
            };
          });
        }
      }
      if (event.code === "ArrowDown" || event.code === "KeyS") {
        crouchActiveRef.current = true;
      }
    };

    const handleKeyUp = (event: KeyboardEvent | ReactKeyboardEvent<HTMLDivElement>) => {
      if (event.code === "ArrowDown" || event.code === "KeyS") {
        crouchActiveRef.current = false;
      }
    };

    const onWindowKeyDown = (event: KeyboardEvent) => handleKeyDown(event);
    const onWindowKeyUp = (event: KeyboardEvent) => handleKeyUp(event);

    document.addEventListener("keydown", onWindowKeyDown, { passive: false, capture: true });
    document.addEventListener("keyup", onWindowKeyUp, { capture: true });
    const element = containerRef.current;
    if (element) {
      const onElementKeyDown = (event: KeyboardEvent) => handleKeyDown(event);
      const onElementKeyUp = (event: KeyboardEvent) => handleKeyUp(event);
      element.addEventListener("keydown", onElementKeyDown);
      element.addEventListener("keyup", onElementKeyUp);
      return () => {
        document.removeEventListener("keydown", onWindowKeyDown, { capture: true });
        document.removeEventListener("keyup", onWindowKeyUp, { capture: true });
        element.removeEventListener("keydown", onElementKeyDown);
        element.removeEventListener("keyup", onElementKeyUp);
      };
    }

    return () => {
      document.removeEventListener("keydown", onWindowKeyDown, { capture: true });
      document.removeEventListener("keyup", onWindowKeyUp, { capture: true });
    };
  }, []);

  useEffect(() => {
    let frameId = 0;
    let lastTime = performance.now();

    const loop = (now: number) => {
      const dt = Math.min(32, now - lastTime);
      lastTime = now;
      const timeScale = dt / 16.6667;

      setGame((previous) => {
        let y = previous.y;
        let velocityY = previous.velocityY;
        const speed = 3.25 * timeScale;
        let obstacles = previous.obstacles
          .map((obstacle) => ({ ...obstacle, x: obstacle.x - speed }))
          .filter((obstacle) => obstacle.x > -60);

        spawnElapsedRef.current += dt;
        if (spawnElapsedRef.current >= spawnCooldownRef.current) {
          obstacleIdRef.current += 1;
          const kind: ObstacleKind = autoplay
            ? autoplayPatternRef.current[
                autoplayPatternIndexRef.current++ % autoplayPatternRef.current.length
              ]
            : Math.random() > 0.32
              ? "envelope"
              : "thread";
          obstacles = [...obstacles, { id: obstacleIdRef.current, kind, x: WIDTH + 16 }];
          spawnElapsedRef.current = 0;
          spawnCooldownRef.current = autoplay ? 640 : 900 + Math.random() * 700;
        }

        const grounded = y <= 0.001;
        const nextObstacle = obstacles.find((obstacle) => {
          const box = obstacleBox(obstacle);
          return box.right >= PLAYER_X - 6;
        });
        const nextObstacleBox = nextObstacle ? obstacleBox(nextObstacle) : null;
        const autoplayCrouch =
          autoplay &&
          grounded &&
          nextObstacle?.kind === "thread" &&
          nextObstacleBox !== null &&
          nextObstacleBox.left <= PLAYER_X + PLAYER_WIDTH + 26 &&
          nextObstacleBox.right >= PLAYER_X - 4;

        if (
          autoplay &&
          grounded &&
          nextObstacle?.kind === "envelope" &&
          nextObstacleBox !== null &&
          nextObstacleBox.left <= PLAYER_X + PLAYER_WIDTH + 34
        ) {
          jumpQueuedRef.current = Math.max(jumpQueuedRef.current, 1);
          velocityY = Math.max(velocityY, 11.2);
          jumpQueuedRef.current = 0;
        }

        if (grounded && jumpQueuedRef.current > 0) {
          velocityY = Math.max(velocityY, 11.2);
          jumpQueuedRef.current = 0;
        }

        y = Math.max(0, y + velocityY * timeScale);
        velocityY -= 0.68 * timeScale;
        if (y === 0 && velocityY < 0) {
          velocityY = 0;
        }

        const crouching = (crouchActiveRef.current || autoplayCrouch) && y === 0;
        const playerHeight = crouching ? CROUCH_HEIGHT : STANDING_HEIGHT;
        const playerBox = {
          left: PLAYER_X,
          right: PLAYER_X + PLAYER_WIDTH,
          top: GROUND_Y - y - playerHeight,
          bottom: GROUND_Y - y,
        };

        const collision = obstacles.some((obstacle) => intersects(playerBox, obstacleBox(obstacle)));
        if (collision) {
          return initialState(
            Math.max(previous.best, Math.floor(previous.score)),
            previous.crashes + 1,
          );
        }

        return {
          ...previous,
          y,
          velocityY,
          crouching,
          obstacles,
          score: previous.score + dt * 0.02,
          best: Math.max(previous.best, Math.floor(previous.score)),
        };
      });

      frameId = window.requestAnimationFrame(loop);
    };

    frameId = window.requestAnimationFrame(loop);
    return () => window.cancelAnimationFrame(frameId);
  }, []);

  const playerHeight = game.crouching ? CROUCH_HEIGHT : STANDING_HEIGHT;
  const score = Math.floor(game.score);

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      className={`w-full max-w-[360px] rounded-2xl border border-border bg-background/80 p-3 shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-primary/60 ${className}`}
      onMouseDown={() => containerRef.current?.focus()}
      onPointerEnter={() => containerRef.current?.focus()}
      aria-label="Inbox runner game. Press W, Up Arrow, or Space to jump. Press S or Down Arrow to crouch."
    >
      <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
        <span>Inbox runner</span>
        <span>W / S / arrows / space</span>
      </div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-[172px] w-full rounded-xl border border-border bg-card"
        role="img"
        aria-label="Stickman inbox runner loading game"
      >
        <defs>
          <pattern id="runner-grid" width="18" height="18" patternUnits="userSpaceOnUse">
            <path d="M18 0H0V18" fill="none" stroke="currentColor" strokeOpacity="0.05" strokeWidth="1" />
          </pattern>
        </defs>

        <rect x="0" y="0" width={WIDTH} height={HEIGHT} fill="url(#runner-grid)" className="text-foreground" />
        <line x1="0" y1={GROUND_Y + 0.5} x2={WIDTH} y2={GROUND_Y + 0.5} stroke="currentColor" strokeOpacity="0.18" />
        <path
          d={`M0 ${GROUND_Y + 10} C 40 ${GROUND_Y + 6}, 80 ${GROUND_Y + 14}, 120 ${GROUND_Y + 10} S 200 ${GROUND_Y + 6}, ${WIDTH} ${GROUND_Y + 10}`}
          fill="none"
          stroke="currentColor"
          strokeOpacity="0.12"
          strokeWidth="2"
        />

        {game.obstacles.map((obstacle) =>
          obstacle.kind === "envelope" ? (
            <g key={obstacle.id} transform={`translate(${obstacle.x} ${GROUND_Y - ENVELOPE_HEIGHT})`} className="text-primary">
              <rect width={ENVELOPE_WIDTH} height={ENVELOPE_HEIGHT} rx="4" fill="currentColor" fillOpacity="0.08" stroke="currentColor" strokeOpacity="0.7" />
              <path d={`M2 4 L${ENVELOPE_WIDTH / 2} ${ENVELOPE_HEIGHT / 2 + 2} L${ENVELOPE_WIDTH - 2} 4`} fill="none" stroke="currentColor" strokeOpacity="0.7" />
            </g>
          ) : (
            <g key={obstacle.id} transform={`translate(${obstacle.x} ${THREAD_TOP})`} className="text-foreground">
              <line x1={THREAD_WIDTH / 2} y1="-20" x2={THREAD_WIDTH / 2} y2="0" stroke="currentColor" strokeOpacity="0.2" strokeDasharray="4 3" />
              <rect width={THREAD_WIDTH} height={THREAD_HEIGHT} rx="8" fill="currentColor" fillOpacity="0.06" stroke="currentColor" strokeOpacity="0.7" />
              <text x={THREAD_WIDTH / 2} y="13" textAnchor="middle" fontSize="9" fill="currentColor" opacity="0.7">
                MAIL
              </text>
            </g>
          ),
        )}

        <g transform={`translate(${PLAYER_X} ${GROUND_Y - game.y})`} className="text-primary">
          {game.crouching ? (
            <>
              <circle cx="10" cy={-18} r="6" fill="none" stroke="currentColor" strokeWidth="2.5" />
              <line x1="15" y1={-14} x2="22" y2={-8} stroke="currentColor" strokeWidth="2.5" />
              <line x1="22" y1={-8} x2="26" y2={-2} stroke="currentColor" strokeWidth="2.5" />
              <line x1="18" y1={-9} x2="8" y2={-3} stroke="currentColor" strokeWidth="2.5" />
              <line x1="18" y1={-9} x2="14" y2={0} stroke="currentColor" strokeWidth="2.5" />
              <line x1="18" y1={-9} x2="26" y2={-1} stroke="currentColor" strokeWidth="2.5" />
            </>
          ) : (
            <>
              <circle cx="12" cy={-36} r="7" fill="none" stroke="currentColor" strokeWidth="2.5" />
              <circle cx="9.2" cy={-37.5} r="1.2" fill="currentColor" />
              <circle cx="14.8" cy={-37.5} r="1.2" fill="currentColor" />
              <path d="M9 -32 Q12 -29 15 -32" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <line x1="12" y1={-29} x2="12" y2={-12} stroke="currentColor" strokeWidth="2.5" />
              <line x1="12" y1={-23} x2="3" y2={-17} stroke="currentColor" strokeWidth="2.5" />
              <line x1="12" y1={-23} x2="22" y2={-18} stroke="currentColor" strokeWidth="2.5" />
              <line x1="12" y1={-12} x2="5" y2={0} stroke="currentColor" strokeWidth="2.5" />
              <line x1="12" y1={-12} x2="21" y2={0} stroke="currentColor" strokeWidth="2.5" />
            </>
          )}
        </g>
      </svg>
      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
        <span>Score {score}</span>
        <span>Best {Math.max(game.best, score)}</span>
        <span>Resets {game.crashes}</span>
      </div>
      {showControlsHint ? (
        <p className="mt-1 text-center text-[10px] uppercase tracking-[0.18em] text-muted-foreground/80">
          {autoplay
            ? "Autoplay is on. Press W, S, arrows, or space to take over."
            : "Click or hover here, then press W, S, arrows, or space."}
        </p>
      ) : null}
    </div>
  );
}
