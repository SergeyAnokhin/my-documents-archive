import { useEffect } from "react";

type KeyMap = Partial<Record<string, () => void>>;

/**
 * Binds keyboard shortcuts while no input/textarea is focused.
 * Keys: "/" | "Escape" | "ArrowLeft" | "ArrowRight" | "?" | "1" | "2" | "+"|"-"
 */
export function useKeyboard(map: KeyMap) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const fn = map[e.key];
      if (fn) {
        e.preventDefault();
        fn();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [map]);
}
