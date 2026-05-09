import { useSyncExternalStore } from "react";

export type LoaderMode = "fun" | "serious";

const LOADER_MODE_KEY = "inboxanchor_loader_mode";
const LOADER_MODE_EVENT = "inboxanchor:loader-mode";

function readStoredMode(): LoaderMode {
  if (typeof window === "undefined") {
    return "fun";
  }
  const stored = window.localStorage.getItem(LOADER_MODE_KEY);
  return stored === "serious" ? "serious" : "fun";
}

function subscribe(callback: () => void) {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  const handleStorage = (event: StorageEvent) => {
    if (event.key === LOADER_MODE_KEY) {
      callback();
    }
  };
  const handleInternal = () => callback();
  window.addEventListener("storage", handleStorage);
  window.addEventListener(LOADER_MODE_EVENT, handleInternal);
  return () => {
    window.removeEventListener("storage", handleStorage);
    window.removeEventListener(LOADER_MODE_EVENT, handleInternal);
  };
}

function getSnapshot(): LoaderMode {
  return readStoredMode();
}

function getServerSnapshot(): LoaderMode {
  return "fun";
}

export function useLoaderMode() {
  const mode = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const setMode = (nextMode: LoaderMode) => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(LOADER_MODE_KEY, nextMode);
    window.dispatchEvent(new Event(LOADER_MODE_EVENT));
  };

  return {
    mode,
    setMode,
    isFunMode: mode === "fun",
  };
}
