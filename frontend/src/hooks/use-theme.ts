import { useState, useEffect, useCallback } from "react";

export type ThemeName = "anchor" | "ocean" | "ember" | "forest" | "violet";

export interface ThemeConfig {
  name: ThemeName;
  label: string;
  preview: string; // primary color for the swatch
}

export const THEMES: ThemeConfig[] = [
  { name: "anchor", label: "Anchor Teal", preview: "oklch(0.72 0.15 185)" },
  { name: "ocean", label: "Deep Ocean", preview: "oklch(0.65 0.18 250)" },
  { name: "ember", label: "Ember", preview: "oklch(0.68 0.20 30)" },
  { name: "forest", label: "Forest", preview: "oklch(0.65 0.18 145)" },
  { name: "violet", label: "Violet Night", preview: "oklch(0.65 0.20 300)" },
];

const THEME_KEY = "inboxanchor_theme";

// CSS variable overrides per theme
const THEME_VARS: Record<ThemeName, Record<string, string>> = {
  anchor: {}, // default — no overrides
  ocean: {
    "--primary": "oklch(0.65 0.18 250)",
    "--primary-foreground": "oklch(0.98 0.005 250)",
    "--accent": "oklch(0.65 0.18 250)",
    "--ring": "oklch(0.65 0.18 250)",
    "--chart-1": "oklch(0.65 0.18 250)",
    "--sidebar-primary": "oklch(0.65 0.18 250)",
    "--sidebar-ring": "oklch(0.65 0.18 250)",
  },
  ember: {
    "--primary": "oklch(0.68 0.20 30)",
    "--primary-foreground": "oklch(0.98 0.005 30)",
    "--accent": "oklch(0.68 0.20 30)",
    "--ring": "oklch(0.68 0.20 30)",
    "--chart-1": "oklch(0.68 0.20 30)",
    "--sidebar-primary": "oklch(0.68 0.20 30)",
    "--sidebar-ring": "oklch(0.68 0.20 30)",
  },
  forest: {
    "--primary": "oklch(0.65 0.18 145)",
    "--primary-foreground": "oklch(0.98 0.005 145)",
    "--accent": "oklch(0.65 0.18 145)",
    "--ring": "oklch(0.65 0.18 145)",
    "--chart-1": "oklch(0.65 0.18 145)",
    "--sidebar-primary": "oklch(0.65 0.18 145)",
    "--sidebar-ring": "oklch(0.65 0.18 145)",
  },
  violet: {
    "--primary": "oklch(0.65 0.20 300)",
    "--primary-foreground": "oklch(0.98 0.005 300)",
    "--accent": "oklch(0.65 0.20 300)",
    "--ring": "oklch(0.65 0.20 300)",
    "--chart-1": "oklch(0.65 0.20 300)",
    "--sidebar-primary": "oklch(0.65 0.20 300)",
    "--sidebar-ring": "oklch(0.65 0.20 300)",
  },
};

function applyTheme(name: ThemeName) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  // Remove all theme overrides first
  const allVars = new Set(Object.values(THEME_VARS).flatMap((v) => Object.keys(v)));
  allVars.forEach((v) => root.style.removeProperty(v));
  // Apply new theme
  const vars = THEME_VARS[name];
  Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v));
}

export function useTheme() {
  const [theme, setThemeState] = useState<ThemeName>("anchor");

  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = localStorage.getItem(THEME_KEY) as ThemeName | null;
    if (saved && THEME_VARS[saved]) {
      setThemeState(saved);
      applyTheme(saved);
    }
  }, []);

  const setTheme = useCallback((name: ThemeName) => {
    setThemeState(name);
    localStorage.setItem(THEME_KEY, name);
    applyTheme(name);
  }, []);

  return { theme, setTheme, themes: THEMES };
}