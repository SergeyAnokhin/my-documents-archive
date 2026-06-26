import { useState, useRef, useEffect } from "react";

const STORAGE_KEY = "lab-panel-width";
const MIN = 300;
const MAX = 900;

/** Draggable width for the right-hand experiments panel, persisted to localStorage. */
export function usePanelResize() {
  const [panelWidth, setPanelWidth] = useState(() => {
    try {
      const v = localStorage.getItem(STORAGE_KEY);
      if (v) return Math.max(MIN, Math.min(MAX, Number(v)));
    } catch {}
    return 440;
  });

  const panelWidthRef = useRef(panelWidth);
  const isResizing = useRef(false);
  const resizeStartX = useRef(0);
  const resizeStartWidth = useRef(panelWidth);

  useEffect(() => { panelWidthRef.current = panelWidth; }, [panelWidth]);

  const onResizerDown = (e: React.MouseEvent) => {
    isResizing.current = true;
    resizeStartX.current = e.clientX;
    resizeStartWidth.current = panelWidth;
    e.preventDefault();
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!isResizing.current) return;
      const dx = resizeStartX.current - e.clientX;
      setPanelWidth(Math.max(MIN, Math.min(MAX, resizeStartWidth.current + dx)));
    };
    const onUp = () => {
      if (isResizing.current) {
        try { localStorage.setItem(STORAGE_KEY, String(panelWidthRef.current)); } catch {}
      }
      isResizing.current = false;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  return { panelWidth, onResizerDown };
}
