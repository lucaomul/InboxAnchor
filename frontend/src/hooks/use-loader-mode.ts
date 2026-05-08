import { useEffect, useState } from "react";

export type LoaderMode = "fun" | "serious";

const LOADER_MODE_KEY = "inboxanchor_loader_mode";

function readStoredMode(): LoaderMode {
  if (typeof window === "undefined") {
    return "fun";
  }
  const stored = window.localStorage.getItem(LOADER_MODE_KEY);
  return stored === "serious" ? "serious" : "fun";
}

export function useLoaderMode() {
  const [mode, setMode] = useState<LoaderMode>(() => readStoredMode());

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(LOADER_MODE_KEY, mode);
  }, [mode]);

  return {
    mode,
    setMode,
    isFunMode: mode === "fun",
  };
}
