import { useState, useRef, useEffect, type MutableRefObject, type RefObject } from "react";
import type { LabImageInfo, LabPreviewResult, LabTransformParams } from "../types";
import { getLabImageInfo, previewLabTransform, applyLabTransform } from "../api/documents";

interface Options {
  docId: number;
  isPdf: boolean;
  zoomRef: MutableRefObject<number>;
  imgRef: RefObject<HTMLImageElement | null>;
  armAutoFit: () => void;
  cropMode: boolean;
  setCropMode: (v: boolean | ((prev: boolean) => boolean)) => void;
  onLog?: (msg: string, kind?: "ok" | "err") => void;
}

export function useImageEdit({
  docId, isPdf, zoomRef, imgRef, armAutoFit,
  cropMode, setCropMode, onLog,
}: Options) {
  const [imageInfo, setImageInfo] = useState<LabImageInfo | null>(null);
  const [outputScale, setOutputScale] = useState(1);
  const [outputQuality, setOutputQuality] = useState(85);
  const [outputRotation, setOutputRotation] = useState(0);
  const [cropRect, setCropRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [previewResult, setPreviewResult] = useState<LabPreviewResult | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isApplying, setIsApplying] = useState(false);
  const [applyDone, setApplyDone] = useState(false);
  const [imgVersion, setImgVersion] = useState(0);

  const cropOverlayRef = useRef<HTMLDivElement>(null);
  const isCroppingRef = useRef(false);
  const cropStartRef = useRef<{ x: number; y: number } | null>(null);
  const autoPreviewCtrl = useRef<AbortController | null>(null);

  useEffect(() => {
    setImageInfo(null);
    getLabImageInfo(docId).then(setImageInfo).catch(() => {});
  }, [docId]);

  // Reset state on document change
  useEffect(() => {
    autoPreviewCtrl.current?.abort();
    autoPreviewCtrl.current = null;
    setOutputScale(1);
    setOutputQuality(85);
    setOutputRotation(0);
    setCropRect(null);
    setPreviewResult(null);
    setIsPreviewing(false);
    setIsApplying(false);
    setApplyDone(false);
  }, [docId]);

  // Global crop mouse tracking (independent from the parent's pan listeners)
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!isCroppingRef.current || !cropOverlayRef.current || !cropStartRef.current) return;
      const rect = cropOverlayRef.current.getBoundingClientRect();
      const z = zoomRef.current;
      const curX = Math.max(0, (e.clientX - rect.left) / z);
      const curY = Math.max(0, (e.clientY - rect.top) / z);
      const imgEl = imgRef.current;
      const maxW = imgEl ? imgEl.naturalWidth : Infinity;
      const maxH = imgEl ? imgEl.naturalHeight : Infinity;
      setCropRect({
        x: Math.round(Math.max(0, Math.min(cropStartRef.current.x, curX))),
        y: Math.round(Math.max(0, Math.min(cropStartRef.current.y, curY))),
        w: Math.round(Math.min(Math.abs(curX - cropStartRef.current.x), maxW)),
        h: Math.round(Math.min(Math.abs(curY - cropStartRef.current.y), maxH)),
      });
    };
    const onUp = () => {
      if (isCroppingRef.current) {
        setCropRect(prev => (prev && prev.w < 5 && prev.h < 5) ? null : prev);
      }
      isCroppingRef.current = false;
      cropStartRef.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [zoomRef, imgRef]);

  const hasTransformChange = outputScale !== 1 || !!cropRect || outputRotation !== 0
    || (imageInfo?.can_adjust_quality === true && outputQuality !== 85);

  // Auto-preview with 400 ms debounce
  useEffect(() => {
    if (!hasTransformChange || isPdf) {
      autoPreviewCtrl.current?.abort();
      autoPreviewCtrl.current = null;
      setPreviewResult(null);
      setIsPreviewing(false);
      return;
    }
    autoPreviewCtrl.current?.abort();
    const ctrl = new AbortController();
    autoPreviewCtrl.current = ctrl;
    setIsPreviewing(true);
    const params: LabTransformParams = {};
    if (outputScale !== 1) params.scale = outputScale;
    if (cropRect) params.crop = cropRect;
    if (imageInfo?.can_adjust_quality && outputQuality !== 85) params.quality = outputQuality;
    if (outputRotation) params.rotation = outputRotation;
    const timer = setTimeout(async () => {
      if (ctrl.signal.aborted) return;
      try {
        const result = await previewLabTransform(docId, params);
        if (!ctrl.signal.aborted) {
          setPreviewResult(result);
          armAutoFit();
          onLog?.(`→ Preview: ${result.width}×${result.height}`, "ok");
        }
      } catch (e) {
        if (!ctrl.signal.aborted) onLog?.(`✗ Preview: ${(e as Error).message}`, "err");
      } finally {
        if (!ctrl.signal.aborted) {
          setIsPreviewing(false);
          autoPreviewCtrl.current = null;
        }
      }
    }, 400);
    return () => { clearTimeout(timer); ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outputRotation, outputScale, cropRect, outputQuality, docId, hasTransformChange, isPdf]);

  const handleCancel = () => {
    autoPreviewCtrl.current?.abort();
    autoPreviewCtrl.current = null;
    setPreviewResult(null);
    setIsPreviewing(false);
    setOutputScale(1);
    setOutputQuality(85);
    setOutputRotation(0);
    setCropRect(null);
    setCropMode(false);
  };

  const handleApply = async () => {
    autoPreviewCtrl.current?.abort();
    autoPreviewCtrl.current = null;
    setIsApplying(true);
    try {
      const params: LabTransformParams = {};
      if (outputScale !== 1) params.scale = outputScale;
      if (cropRect) params.crop = cropRect;
      if (imageInfo?.can_adjust_quality && outputQuality !== 85) params.quality = outputQuality;
      if (outputRotation) params.rotation = outputRotation;
      const result = await applyLabTransform(docId, params);
      setImageInfo(prev => prev
        ? { ...prev, width: result.width, height: result.height, file_size: result.file_size }
        : prev);
      setPreviewResult(null);
      setOutputScale(1);
      setOutputQuality(85);
      setOutputRotation(0);
      setCropRect(null);
      setCropMode(false);
      setApplyDone(true);
      setImgVersion(v => v + 1);
      armAutoFit();
      window.dispatchEvent(new CustomEvent("docintell:document-image-changed", { detail: { id: docId } }));
      onLog?.(`✓ Applied: ${result.width}×${result.height}`, "ok");
      setTimeout(() => setApplyDone(false), 2500);
    } catch (e) {
      onLog?.(`✗ Apply: ${(e as Error).message}`, "err");
    } finally {
      setIsApplying(false);
    }
  };

  const onCropOverlayMouseDown = (e: React.MouseEvent) => {
    if (!cropMode || !cropOverlayRef.current) return;
    const rect = cropOverlayRef.current.getBoundingClientRect();
    const z = zoomRef.current;
    cropStartRef.current = {
      x: Math.max(0, (e.clientX - rect.left) / z),
      y: Math.max(0, (e.clientY - rect.top) / z),
    };
    isCroppingRef.current = true;
    setCropRect(null);
    e.preventDefault();
    e.stopPropagation();
  };

  return {
    imageInfo,
    outputScale, setOutputScale,
    outputQuality, setOutputQuality,
    outputRotation, setOutputRotation,
    cropRect, setCropRect,
    previewResult,
    isPreviewing,
    isApplying,
    applyDone,
    imgVersion,
    hasTransformChange,
    cropOverlayRef,
    handleCancel,
    handleApply,
    onCropOverlayMouseDown,
  };
}
