import { useState, useCallback } from "react";

const KEY_PREFIX = "docintell:search_history:";
const MAX_KEY = "docintell:prefs:search_history_max";
const DEFAULT_MAX = 10;

function storedMax(): number {
  const v = localStorage.getItem(MAX_KEY);
  const n = v ? parseInt(v, 10) : NaN;
  return Number.isFinite(n) && n > 0 ? Math.min(n, 50) : DEFAULT_MAX;
}

function storedItems(mode: string): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY_PREFIX + mode) ?? "[]");
  } catch { return []; }
}

export function useSearchHistory(mode: "search" | "ask") {
  const [items, setItems] = useState<string[]>(() => storedItems(mode));
  const [max, setMaxState] = useState(storedMax);

  const save = useCallback((query: string) => {
    if (!query.trim()) return;
    const limit = storedMax();
    const next = [query, ...storedItems(mode).filter(h => h !== query)].slice(0, limit);
    localStorage.setItem(KEY_PREFIX + mode, JSON.stringify(next));
    setItems(next);
  }, [mode]);

  const clear = useCallback(() => {
    localStorage.removeItem(KEY_PREFIX + mode);
    setItems([]);
  }, [mode]);

  const setMax = useCallback((n: number) => {
    const clamped = Math.max(1, Math.min(50, n));
    localStorage.setItem(MAX_KEY, String(clamped));
    setMaxState(clamped);
    // trim both histories to new max
    (["search", "ask"] as const).forEach(m => {
      const cur = storedItems(m);
      if (cur.length > clamped) {
        localStorage.setItem(KEY_PREFIX + m, JSON.stringify(cur.slice(0, clamped)));
      }
    });
    // re-read this mode's items in case they were trimmed
    setItems(storedItems(mode));
  }, [mode]);

  return { items, save, clear, max, setMax };
}
