"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, tokenStore } from "@/lib/api/client";

export interface MatrixSettings {
  enabled: boolean;
  speed: number;
  density: number;
  opacity: number;
  respect_reduced_motion: boolean;
  renderer: "auto" | "pty" | "port";
}

export interface AppSettings {
  theme: "dark" | "light";
  sidebar_collapsed: boolean;
  matrix: MatrixSettings;
  default_model: string;
  streaming: boolean;
  voice_enabled: boolean;
  memory_enabled: boolean;
  notifications: boolean;
  privacy: { save_explicit_instructions: boolean };
}

export const DEFAULT_SETTINGS: AppSettings = {
  theme: "dark",
  sidebar_collapsed: false,
  matrix: {
    enabled: true,
    speed: 5,
    density: 5,
    opacity: 0.22,
    respect_reduced_motion: true,
    renderer: "auto",
  },
  default_model: "",
  streaming: true,
  voice_enabled: true,
  memory_enabled: true,
  notifications: true,
  privacy: { save_explicit_instructions: true },
};

const STORAGE_KEY = "armx.settings.cache";
const THEME_KEY = "armx.theme";

export type SettingsPatch = Omit<Partial<AppSettings>, "matrix" | "privacy"> & {
  matrix?: Partial<MatrixSettings>;
  privacy?: Partial<AppSettings["privacy"]>;
};

interface PreferencesValue {
  settings: AppSettings;
  loading: boolean;
  update: (patch: SettingsPatch) => Promise<void>;
  reload: () => Promise<void>;
}

const PreferencesContext = createContext<PreferencesValue | null>(null);

function merge(base: AppSettings, patch: object): AppSettings {
  const source = patch as Record<string, unknown>;
  const next: AppSettings = { ...base, ...(source as Partial<AppSettings>) };
  next.matrix = { ...base.matrix, ...((source.matrix as Partial<MatrixSettings>) || {}) };
  next.privacy = { ...base.privacy, ...((source.privacy as Partial<AppSettings["privacy"]>) || {}) };
  return next;
}

function applyTheme(theme: "dark" | "light") {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(theme);
  localStorage.setItem(THEME_KEY, theme);
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<AppSettings>(() => {
    if (typeof window === "undefined") return DEFAULT_SETTINGS;
    try {
      const cached = localStorage.getItem(STORAGE_KEY);
      if (cached) return merge(DEFAULT_SETTINGS, JSON.parse(cached));
    } catch {
      // A corrupt cache must never break the app shell.
    }
    const theme = localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
    return { ...DEFAULT_SETTINGS, theme };
  });
  const [loading, setLoading] = useState(false);

  const persistLocal = useCallback((next: AppSettings) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    applyTheme(next.theme);
  }, []);

  const reload = useCallback(async () => {
    if (!tokenStore.access() && !tokenStore.refresh()) return;
    setLoading(true);
    try {
      const data = await api.get<{ settings: AppSettings }>("/preferences");
      const next = merge(DEFAULT_SETTINGS, data.settings);
      setSettings(next);
      persistLocal(next);
    } catch {
      // Offline/local use keeps the cached settings; the UI never claims a save.
    } finally {
      setLoading(false);
    }
  }, [persistLocal]);

  useEffect(() => {
    applyTheme(settings.theme);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = useCallback(
    async (patch: SettingsPatch) => {
      const next = merge(settings, patch);
      setSettings(next);
      persistLocal(next);
      if (!tokenStore.access()) return;
      try {
        const data = await api.patch<{ settings: AppSettings }>("/preferences", { settings: patch });
        const confirmed = merge(DEFAULT_SETTINGS, data.settings);
        setSettings(confirmed);
        persistLocal(confirmed);
      } catch {
        // The local cache still works; Settings shows the error through the query.
        await reload();
      }
    },
    [persistLocal, reload, settings],
  );

  const value = useMemo(() => ({ settings, loading, update, reload }), [settings, loading, update, reload]);
  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesValue {
  const ctx = useContext(PreferencesContext);
  if (!ctx) throw new Error("usePreferences must be used inside PreferencesProvider");
  return ctx;
}
