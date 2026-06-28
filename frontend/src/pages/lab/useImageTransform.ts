import { RefObject, useCallback, useEffect, useRef, useState } from "react";

interface Options {
  canvasRef: RefObject<HTMLDivElement | null>;
  imgRef: RefObject<HTMLImageElement | null>;
  /** Disable canvas panning while cropping or for PDFs. */
  cropMode: boolean;
  isPdf: boolean;
  /** Changing this (e.g. the document id) re-arms auto-fit on next image load. */
  resetKey?: string;
}

/**
 * Zoom + pan for the OCR Lab image canvas: wheel-zoom at cursor, button zoom,
 * fit-on-load, and drag-to-pan. Owns the wheel and pan listeners; `zoomRef`
 * exposes the live zoom for the crop overlay, which lives in the page.
 */
export function useImageTransform({ canvasRef, imgRef, cropMode, isPdf, resetKey }: Options) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const zoomRef = useRef(zoom);
  useEffect(() => { zoomRef.current = zoom; }, [zoom]);

  const didAutoFitRef = useRef(false);
  const panStartRef = useRef<{ mouseX: number; mouseY: number; panX: number; panY: number } | null>(null);

  // Re-arm auto-fit whenever the document changes.
  useEffect(() => { didAutoFitRef.current = false; }, [resetKey]);

  // Mouse-wheel zoom at cursor.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const rect = canvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      setZoom(prevZoom => {
        const newZoom = Math.max(0.05, Math.min(20, prevZoom * factor));
        setPan(prevPan => ({
          x: mouseX - (mouseX - prevPan.x) * (newZoom / prevZoom),
          y: mouseY - (mouseY - prevPan.y) * (newZoom / prevZoom),
        }));
        return newZoom;
      });
    };
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, [canvasRef]);

  // Drag-to-pan.
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!panStartRef.current) return;
      const dx = e.clientX - panStartRef.current.mouseX;
      const dy = e.clientY - panStartRef.current.mouseY;
      setPan({ x: panStartRef.current.panX + dx, y: panStartRef.current.panY + dy });
    };
    const onUp = () => {
      if (panStartRef.current && canvasRef.current) {
        delete canvasRef.current.dataset.panning;
      }
      panStartRef.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [canvasRef]);

  const zoomAround = useCallback((factor: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const cx = canvas.clientWidth / 2;
    const cy = canvas.clientHeight / 2;
    setZoom(prevZoom => {
      const newZoom = Math.max(0.05, Math.min(20, prevZoom * factor));
      setPan(prevPan => ({
        x: cx - (cx - prevPan.x) * (newZoom / prevZoom),
        y: cy - (cy - prevPan.y) * (newZoom / prevZoom),
      }));
      return newZoom;
    });
  }, [canvasRef]);

  const handleImgLoad = useCallback(() => {
    if (didAutoFitRef.current) return;
    didAutoFitRef.current = true;
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || img.naturalWidth === 0) return;
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    const iw = img.naturalWidth;
    const ih = img.naturalHeight;
    const fitZoom = Math.max(0.05, Math.min((cw - 32) / iw, (ch - 32) / ih));
    setZoom(fitZoom);
    setPan({ x: (cw - iw * fitZoom) / 2, y: (ch - ih * fitZoom) / 2 });
  }, [canvasRef, imgRef]);

  const handleZoomReset = useCallback(() => {
    didAutoFitRef.current = false;
    handleImgLoad();
  }, [handleImgLoad]);

  /** Call before changing imgSrc so the next onLoad auto-fits the new image. */
  const armAutoFit = useCallback(() => {
    didAutoFitRef.current = false;
  }, []);

  const onCanvasMouseDown = useCallback((e: React.MouseEvent) => {
    if (cropMode || isPdf || e.button !== 0) return;
    panStartRef.current = { mouseX: e.clientX, mouseY: e.clientY, panX: pan.x, panY: pan.y };
    if (canvasRef.current) canvasRef.current.dataset.panning = "true";
    e.preventDefault();
  }, [cropMode, isPdf, pan.x, pan.y, canvasRef]);

  return { zoom, pan, zoomRef, zoomAround, handleImgLoad, handleZoomReset, armAutoFit, onCanvasMouseDown };
}
