import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, ZoomIn, ZoomOut, Maximize, Play, Scale,
  Terminal, Scissors, Check, RotateCcw, RotateCw,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { useT } from "../i18n";
import {
  getDocument, getLabMethods, listProviders,
  runLabOcr, runLabVision, runLabJudge, saveLabResult,
  getLabImageInfo, previewLabTransform, applyLabTransform,
} from "../api/documents";
import type {
  Document, AIProvider, LabMethods, LabResult, LabJudgeResult,
  LabImageInfo, LabPreviewResult, LabTransformParams,
} from "../types";
import { formatMs, formatFileSize, VISION_CAPABLE, uid } from "./lab/labUtils";
import { useLogs } from "./lab/useLogs";
import { usePanelResize } from "./lab/usePanelResize";
import { useImageTransform } from "./lab/useImageTransform";
import { ResultsList } from "./lab/ResultsList";
import { JudgePanel } from "./lab/JudgePanel";
import { FloatingTextModal } from "./lab/FloatingTextModal";
import "./LabPage.css";

export function LabPage() {
  const { t, lang } = useT();
  const lab = t.lab;
  const { id } = useParams();
  const docId = Number(id);
  const navigate = useNavigate();

  const [doc, setDoc] = useState<Document | null>(null);
  const [methods, setMethods] = useState<LabMethods | null>(null);
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [results, setResults] = useState<LabResult[]>([]);

  const [runningOcr, setRunningOcr] = useState<Set<string>>(new Set());
  const [runningVision, setRunningVision] = useState<Set<number>>(new Set());

  // Judge
  const [judgeProviders, setJudgeProviders] = useState<number[]>([]);
  const [judgingIds, setJudgingIds] = useState<number[]>([]);
  const [judgeResults, setJudgeResults] = useState<Record<number, LabJudgeResult>>({});
  const [judgeErrors, setJudgeErrors] = useState<Record<number, string>>({});

  const [savingId, setSavingId] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  // ── Image canvas refs ─────────────────────────────────────────────────────────
  const canvasRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);

  // ── Image tools ──────────────────────────────────────────────────────────────
  const [imageInfo, setImageInfo] = useState<LabImageInfo | null>(null);
  const [outputScale, setOutputScale] = useState<number>(1);
  const [outputQuality, setOutputQuality] = useState<number>(85);
  const [outputRotation, setOutputRotation] = useState<number>(0);
  const [cropMode, setCropMode] = useState(false);
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
  // Stable keyboard listener — updated every render, registered once
  const keyHandlerRef = useRef<(e: KeyboardEvent) => void>(() => {});

  // ── Zoom / Pan (extracted) ─────────────────────────────────────────────────────
  const isPdf = doc?.mime_type === "application/pdf" || !!doc?.filename.toLowerCase().endsWith(".pdf");
  const {
    zoom, pan, zoomRef, zoomAround, handleImgLoad, handleZoomReset, armAutoFit, onCanvasMouseDown,
  } = useImageTransform({ canvasRef, imgRef, cropMode, isPdf, resetKey: id });

  // ── Panel resize ─────────────────────────────────────────────────────────────
  const { panelWidth, onResizerDown } = usePanelResize();

  // ── Keyboard listener — stable registration, handler ref updated every render ─
  useEffect(() => {
    const handler = (e: KeyboardEvent) => keyHandlerRef.current(e);
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // ── Floating text modal ──────────────────────────────────────────────────────
  const [expandedResult, setExpandedResult] = useState<LabResult | null>(null);
  const [modalPos, setModalPos] = useState({ x: 24, y: 80 });
  const modalDragStart = useRef<{ mx: number; my: number; px: number; py: number } | null>(null);

  const onModalDragStart = (e: React.MouseEvent, curPos: { x: number; y: number }) => {
    modalDragStart.current = { mx: e.clientX, my: e.clientY, px: curPos.x, py: curPos.y };
    e.preventDefault();
  };

  // ── Global mouse handlers (modal drag, crop) ─────────────────────────────────
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (modalDragStart.current) {
        const dx = e.clientX - modalDragStart.current.mx;
        const dy = e.clientY - modalDragStart.current.my;
        setModalPos({
          x: Math.max(0, modalDragStart.current.px + dx),
          y: Math.max(0, modalDragStart.current.py + dy),
        });
      }
      if (isCroppingRef.current && cropOverlayRef.current && cropStartRef.current) {
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
      }
    };
    const onUp = () => {
      modalDragStart.current = null;
      if (isCroppingRef.current) {
        // discard tiny selections
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
  }, []);

  // ── Logs ─────────────────────────────────────────────────────────────────────
  const { logs, showLogs, setShowLogs, addLog, clearLogs, logsEndRef } = useLogs();

  // ── Data loading ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!docId) return;
    getDocument(docId).then(setDoc).catch(() => {});
    getLabMethods().then(setMethods).catch(() => {});
    listProviders().then(setProviders).catch(() => {});
    getLabImageInfo(docId).then(setImageInfo).catch(() => {});
  }, [docId]);

  const visionProviders = useMemo(
    () => providers.filter(
      p => p.enabled
        && (p.task_type === "vision" || p.task_type === "both")
        && VISION_CAPABLE.includes(p.provider_type),
    ),
    [providers],
  );

  const premiumProviders = useMemo(
    () => providers.filter(p => p.enabled && p.task_type === "premium"),
    [providers],
  );

  const bestLabels = useMemo(
    () => new Set(Object.values(judgeResults).map(r => r.best)),
    [judgeResults],
  );

  useEffect(() => {
    if (judgeProviders.length === 0 && premiumProviders.length > 0) {
      setJudgeProviders(premiumProviders.filter(p => p.enabled).map(p => p.id));
    }
  }, [premiumProviders]); // eslint-disable-line react-hooks/exhaustive-deps

  const upsert = (r: LabResult) =>
    setResults(prev => [...prev.filter(p => p.label !== r.label), r]);

  // ── Crop overlay mousedown ────────────────────────────────────────────────────
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

  // ── OCR / Vision handlers ─────────────────────────────────────────────────────
  const handleOcr = async (method: string) => {
    setRunningOcr(prev => new Set(prev).add(method));
    addLog(`→ OCR [${method}]`);
    try {
      const res = await runLabOcr(docId, method);
      upsert({ id: uid(), kind: "ocr", label: method, text: res.text, ms: res.ms, fields: res.fields || undefined });
      addLog(`← OCR [${method}]: ${res.text.length} chars · ${formatMs(res.ms)}`, "ok");
    } catch (e) {
      upsert({ id: uid(), kind: "ocr", label: method, text: `⚠️ ${lab.failed}: ${(e as Error).message}`, ms: 0 });
      addLog(`✗ OCR [${method}]: ${(e as Error).message}`, "err");
    } finally {
      setRunningOcr(prev => { const s = new Set(prev); s.delete(method); return s; });
    }
  };

  const handleVision = async (p: AIProvider) => {
    setRunningVision(prev => new Set(prev).add(p.id));
    addLog(`→ Vision [${p.name}]`);
    try {
      const res = await runLabVision(docId, p.id);
      upsert({
        id: uid(), kind: "vision", label: p.name, providerId: p.id,
        providerModel: res.model_name || p.model || undefined,
        text: res.text, ms: res.ms, cost: res.cost,
        tokens_in: res.tokens_in, tokens_out: res.tokens_out,
        fields: res.fields || undefined,
      });
      const costStr = res.cost != null && res.cost > 0 ? ` · $${res.cost.toFixed(5)}` : "";
      const tokStr = res.tokens_in ? ` · ${res.tokens_in}+${res.tokens_out} tok` : "";
      addLog(`← Vision [${p.name}]: ${res.text.length} chars · ${formatMs(res.ms)}${tokStr}${costStr}`, "ok");
    } catch (e) {
      upsert({ id: uid(), kind: "vision", label: p.name, providerId: p.id, text: `⚠️ ${lab.failed}: ${(e as Error).message}`, ms: 0 });
      addLog(`✗ Vision [${p.name}]: ${(e as Error).message}`, "err");
    } finally {
      setRunningVision(prev => { const s = new Set(prev); s.delete(p.id); return s; });
    }
  };

  const handleSave = async (r: LabResult) => {
    setSavingId(r.id);
    setSavedId(null);
    const modelLabel = [r.label, r.providerModel].filter(Boolean).join(" · ");
    try {
      await saveLabResult({ doc_id: docId, text: r.text, fields: r.fields, model_name: modelLabel });
      setSavedId(r.id);
      addLog(`✓ Saved [${r.label}] to document`, "ok");
      setTimeout(() => setSavedId(id => id === r.id ? null : id), 2500);
    } catch (e) {
      addLog(`✗ Save [${r.label}]: ${(e as Error).message}`, "err");
    } finally {
      setSavingId(id => id === r.id ? null : id);
    }
  };

  const handleSaveJudge = async (providerId: number, providerName: string, result: LabJudgeResult) => {
    const fakeId = `judge-${providerId}`;
    setSavingId(fakeId);
    setSavedId(null);
    try {
      const bestText = results.find(r => r.label === result.best)?.text ?? "";
      await saveLabResult({ doc_id: docId, text: result.corrected || bestText, fields: result.fields, model_name: `Judge: ${providerName}` });
      setSavedId(fakeId);
      addLog(`✓ Saved judge [${providerName}] corrected text to document`, "ok");
      setTimeout(() => setSavedId(id => id === fakeId ? null : id), 2500);
    } catch (e) {
      addLog(`✗ Save judge [${providerName}]: ${(e as Error).message}`, "err");
    } finally {
      setSavingId(id => id === fakeId ? null : id);
    }
  };

  const handleJudge = async () => {
    const toRun = judgeProviders.filter(id => premiumProviders.some(p => p.id === id));
    if (toRun.length === 0 || results.length < 2) return;
    setJudgingIds(toRun);
    setJudgeErrors({});
    setJudgeResults(prev => {
      const next = { ...prev };
      toRun.forEach(id => delete next[id]);
      return next;
    });

    await Promise.all(toRun.map(async (providerId) => {
      const provider = premiumProviders.find(p => p.id === providerId)!;
      const hasVision = VISION_CAPABLE.includes(provider.provider_type);
      addLog(`→ Judge [${provider.name}]${hasVision ? " +image" : ""} on ${results.length} candidates`);
      try {
        const res = await runLabJudge({
          doc_id: docId,
          provider_id: providerId,
          use_image: hasVision,
          language: lang,
          candidates: results.map(r => ({ label: r.label, text: r.text })),
        });
        setJudgeResults(prev => ({ ...prev, [providerId]: res }));
        const costStr = res.cost > 0 ? ` · $${res.cost.toFixed(5)}` : "";
        addLog(`← Judge [${provider.name}]: best="${res.best}" · ${formatMs(res.ms)}${costStr}`, "ok");
      } catch (e) {
        setJudgeErrors(prev => ({ ...prev, [providerId]: (e as Error).message }));
        addLog(`✗ Judge [${provider.name}]: ${(e as Error).message}`, "err");
      } finally {
        setJudgingIds(prev => prev.filter(id => id !== providerId));
      }
    }));
  };

  const hasTransformChange = outputScale !== 1 || !!cropRect || outputRotation !== 0 || (imageInfo?.can_adjust_quality && outputQuality !== 85);

  // ── Auto-preview on transform change (400 ms debounce) ───────────────────────
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
    const t = setTimeout(async () => {
      if (ctrl.signal.aborted) return;
      try {
        const result = await previewLabTransform(docId, params);
        if (!ctrl.signal.aborted) {
          setPreviewResult(result);
          armAutoFit();
          addLog(`→ Preview: ${result.width}×${result.height} · ${formatFileSize(result.file_size)}`, "ok");
        }
      } catch (e) {
        if (!ctrl.signal.aborted) addLog(`✗ Preview: ${(e as Error).message}`, "err");
      } finally {
        if (!ctrl.signal.aborted) {
          setIsPreviewing(false);
          autoPreviewCtrl.current = null;
        }
      }
    }, 400);
    return () => { clearTimeout(t); ctrl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outputRotation, outputScale, cropRect, outputQuality, docId, hasTransformChange, isPdf]);

  // ── Image transform handlers ──────────────────────────────────────────────────
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
    if (!window.confirm(lab.applyConfirm)) return;
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
      setImageInfo(prev => prev ? { ...prev, width: result.width, height: result.height, file_size: result.file_size } : prev);
      setPreviewResult(null);
      setOutputScale(1);
      setOutputQuality(85);
      setOutputRotation(0);
      setCropRect(null);
      setCropMode(false);
      setApplyDone(true);
      setImgVersion(v => v + 1);
      armAutoFit();
      addLog(`✓ Applied: ${result.width}×${result.height} · ${formatFileSize(result.file_size)}`, "ok");
      setTimeout(() => setApplyDone(false), 2500);
    } catch (e) {
      addLog(`✗ Apply: ${(e as Error).message}`, "err");
    } finally {
      setIsApplying(false);
    }
  };

  // Update keyboard handler every render so it always closes over fresh state
  keyHandlerRef.current = (e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (e.key === "+" || e.key === "=") { e.preventDefault(); zoomAround(1.25); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomAround(1 / 1.25); }
    else if (e.key === " ") { e.preventDefault(); handleZoomReset(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); setOutputRotation(r => (r - 90 + 360) % 360); }
    else if (e.key === "ArrowRight") { e.preventDefault(); setOutputRotation(r => (r + 90) % 360); }
    else if (e.key === "Escape") {
      e.preventDefault();
      if (cropMode) { setCropMode(false); setCropRect(null); }
      else if (hasTransformChange || !!previewResult) { handleCancel(); }
      else { navigate("/"); }
    } else if (e.key === "Enter" && (hasTransformChange || !!previewResult) && !isApplying) {
      e.preventDefault();
      handleApply();
    }
  };

  const downloadUrl = `/api/documents/${docId}/download?inline=1`;
  const imgSrc = previewResult
    ? `data:image/jpeg;base64,${previewResult.image_b64}`
    : `${downloadUrl}&v=${imgVersion}`;

  return (
    <div className="lab">
      {/* Top bar */}
      <header className="lab-topbar">
        <Button variant="ghost" size="sm" icon={<ArrowLeft size={15} />} onClick={() => navigate("/")}>
          {lab.back}
        </Button>
        <div className="lab-title">
          <span className="lab-title-main">{lab.title}</span>
          <span className="lab-title-sub">{doc?.filename ?? ""}</span>
        </div>
      </header>

      <div className="lab-body" style={{ gridTemplateColumns: `1fr 6px ${panelWidth}px` }}>
        {/* Left — document */}
        <div className="lab-doc">
          <div className="lab-doc-toolbar">
            <button className="icon-btn" title={`${lab.zoomOut} (−)`} onClick={() => zoomAround(1 / 1.25)}>
              <ZoomOut size={16} />
            </button>
            <span className="text-xs text-muted" style={{ minWidth: 42, textAlign: "center" }}>
              {Math.round(zoom * 100)}%
            </span>
            <button className="icon-btn" title={`${lab.zoomIn} (+)`} onClick={() => zoomAround(1.25)}>
              <ZoomIn size={16} />
            </button>
            <button className="icon-btn" title={`${lab.resetZoom} (Space)`} onClick={handleZoomReset}>
              <Maximize size={16} />
            </button>
            {!isPdf && (
              <>
                <div className="lab-toolbar-sep" />
                <button
                  className={`icon-btn${cropMode ? " active" : ""}`}
                  title={cropMode ? lab.cropClear : `${lab.cropTool} — ${lab.cropHint}`}
                  onClick={() => { setCropMode(m => !m); if (cropMode) setCropRect(null); }}
                >
                  <Scissors size={16} />
                </button>
              </>
            )}
            {imageInfo && (
              <span className="lab-img-info text-xs text-muted">
                {previewResult
                  ? `${previewResult.width}×${previewResult.height} · ${formatFileSize(previewResult.file_size)}`
                  : `${imageInfo.width}×${imageInfo.height} · ${formatFileSize(imageInfo.file_size)}`
                }
              </span>
            )}
            {isPreviewing && (
              <span className="lab-preview-badge lab-preview-badge--loading">{lab.previewTag}</span>
            )}
            {previewResult && !isPreviewing && (
              <span className="lab-preview-badge">{lab.previewTag}</span>
            )}
          </div>

          {!isPdf && (
            <div className="lab-doc-toolbar2">
              <span className="lab-tool2-label text-xs">{lab.resize}</span>
              <select
                className="lab-select2"
                value={String(outputScale)}
                onChange={e => setOutputScale(Number(e.target.value))}
              >
                <option value="1">100% — {lab.original}</option>
                <option value="0.75">75%</option>
                <option value="0.5">50% — ÷2</option>
                <option value="0.25">25% — ÷4</option>
                <option value="0.1">10% — ÷10</option>
              </select>
              {imageInfo?.can_adjust_quality && (
                <>
                  <div className="lab-toolbar-sep" />
                  <span className="lab-tool2-label text-xs">{lab.quality}</span>
                  <input
                    type="range" min="10" max="95" step="5"
                    value={outputQuality}
                    onChange={e => setOutputQuality(Number(e.target.value))}
                    className="lab-slider2"
                  />
                  <span className="text-xs" style={{ minWidth: 22, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{outputQuality}</span>
                </>
              )}
              <div className="lab-toolbar-sep" />
              <button
                className="icon-btn"
                title={`${lab.rotateLeft} (←)`}
                onClick={() => setOutputRotation(r => (r - 90 + 360) % 360)}
              >
                <RotateCcw size={15} />
              </button>
              {outputRotation !== 0 && (
                <span className="text-xs text-muted" style={{ minWidth: 30, textAlign: "center" }}>
                  {outputRotation}°
                </span>
              )}
              <button
                className="icon-btn"
                title={`${lab.rotateRight} (→)`}
                onClick={() => setOutputRotation(r => (r + 90) % 360)}
              >
                <RotateCw size={15} />
              </button>
              {cropMode && cropRect && cropRect.w > 0 && (
                <>
                  <div className="lab-toolbar-sep" />
                  <span className="text-xs text-muted">{lab.cropSelected}: {cropRect.w}×{cropRect.h}</span>
                </>
              )}
              {(hasTransformChange || !!previewResult) && (
                <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                  <Button
                    variant="ghost" size="sm"
                    title={`${lab.cancelEdit} (Esc)`}
                    onClick={handleCancel}
                    disabled={isApplying}
                  >
                    {lab.cancelEdit}
                  </Button>
                  <Button
                    variant="primary" size="sm"
                    icon={<Check size={13} />}
                    loading={isApplying}
                    title={`${applyDone ? lab.applyDone : lab.applyBtn} (Enter)`}
                    onClick={handleApply}
                  >
                    {applyDone ? lab.applyDone : lab.applyBtn}
                  </Button>
                </div>
              )}
            </div>
          )}

          <div
            className="lab-doc-canvas"
            ref={canvasRef}
            onMouseDown={onCanvasMouseDown}
            style={{ cursor: cropMode ? "crosshair" : "grab" }}
          >
            {isPdf ? (
              <iframe src={downloadUrl} title={doc?.filename} className="lab-doc-pdf" />
            ) : (
              <div
                className="lab-doc-viewer"
                ref={viewerRef}
                style={{
                  transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                  transformOrigin: "0 0",
                }}
              >
                <div className="lab-img-container">
                  <img
                    ref={imgRef}
                    src={imgSrc}
                    alt={doc?.filename}
                    className="lab-doc-img"
                    onLoad={handleImgLoad}
                    draggable={false}
                  />
                  {cropMode && !previewResult && (
                    <div
                      className="lab-crop-overlay"
                      ref={cropOverlayRef}
                      onMouseDown={onCropOverlayMouseDown}
                    >
                      {cropRect && cropRect.w > 0 && cropRect.h > 0 && (
                        <div
                          className="lab-crop-selection"
                          style={{
                            left: cropRect.x,
                            top: cropRect.y,
                            width: cropRect.w,
                            height: cropRect.h,
                          }}
                        >
                          <span className="lab-crop-label">{cropRect.w}×{cropRect.h}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Drag handle */}
        <div className="lab-resizer" onMouseDown={onResizerDown} />

        {/* Right — experiments */}
        <aside className="lab-panel">
          <div style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 16 }}>
            <p className="lab-subtitle" style={{ flex: 1, margin: 0 }}>{lab.subtitle}</p>
            <button
              className={`lab-logs-btn${showLogs ? " active" : ""}`}
              onClick={() => setShowLogs(s => !s)}
              title={lab.logs}
            >
              <Terminal size={13} />
              {logs.length > 0 && <span className="lab-logs-count">{logs.length}</span>}
            </button>
          </div>

          {/* Log panel */}
          {showLogs && (
            <div className="lab-logs-panel">
              <div className="lab-logs-header">
                <span>{lab.logs}</span>
                <button className="lab-logs-clear" onClick={clearLogs}>{lab.clearLogs}</button>
              </div>
              <div className="lab-logs-body">
                {logs.length === 0 ? (
                  <span className="lab-logs-empty">—</span>
                ) : (
                  logs.map(l => (
                    <div key={l.id} className={`lab-log-line ${l.kind}`}>
                      <span className="lab-log-ts">{l.ts}</span>
                      <span className="lab-log-msg">{l.msg}</span>
                    </div>
                  ))
                )}
                <div ref={logsEndRef} />
              </div>
            </div>
          )}

          {/* Local OCR */}
          <section className="lab-section">
            <h3 className="lab-section-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {lab.localOcr}
              {methods?.worker_reachable && (
                <span className="status-dot done pulse" title="Compute-сервис доступен" style={{ marginTop: 1 }} />
              )}
            </h3>
            <div className="lab-actions-row">
              {(methods?.ocr_methods ?? ["tesseract"]).map(m => (
                <Button
                  key={m}
                  variant="secondary"
                  size="sm"
                  icon={<Play size={13} />}
                  loading={runningOcr.has(m)}
                  onClick={() => handleOcr(m)}
                >
                  {m}
                </Button>
              ))}
            </div>
            {methods && !methods.worker_available && (
              <p className="text-xs text-muted" style={{ marginTop: 6 }}>
                {methods.worker_reachable ? lab.workerNoEasyocr : lab.workerOffline}
              </p>
            )}
          </section>

          {/* Vision OCR */}
          <section className="lab-section">
            <h3 className="lab-section-title">{lab.visionOcr}</h3>
            {visionProviders.length === 0 ? (
              <p className="text-xs text-muted">{lab.noVisionProviders}</p>
            ) : (
              <div className="lab-provider-list">
                {visionProviders.map(p => (
                  <div key={p.id} className="lab-provider-row">
                    <span className="lab-provider-name">{p.name}</span>
                    <Button
                      variant="secondary" size="sm"
                      icon={<Play size={13} />}
                      loading={runningVision.has(p.id)}
                      onClick={() => handleVision(p)}
                    >
                      {lab.run}
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Results */}
          <section className="lab-section">
            <h3 className="lab-section-title">{t.recognizedText}</h3>
            <ResultsList
              results={results}
              bestLabels={bestLabels}
              savingId={savingId}
              savedId={savedId}
              onSave={handleSave}
              onExpand={r => { setExpandedResult(r); setModalPos({ x: 24, y: 80 }); }}
              onRemove={id => setResults(prev => prev.filter(x => x.id !== id))}
            />
          </section>

          {/* Judge */}
          <section className="lab-section">
            <h3 className="lab-section-title"><Scale size={14} /> {lab.judge}</h3>
            <JudgePanel
              premiumProviders={premiumProviders}
              judgeProviders={judgeProviders}
              setJudgeProviders={setJudgeProviders}
              judgingIds={judgingIds}
              judgeResults={judgeResults}
              judgeErrors={judgeErrors}
              resultsCount={results.length}
              savingId={savingId}
              savedId={savedId}
              onJudge={handleJudge}
              onSaveJudge={handleSaveJudge}
            />
          </section>
        </aside>
      </div>

      {/* Floating text modal */}
      {expandedResult && (
        <FloatingTextModal
          result={expandedResult}
          pos={modalPos}
          savingId={savingId}
          savedId={savedId}
          onDragStart={onModalDragStart}
          onSave={handleSave}
          onClose={() => setExpandedResult(null)}
        />
      )}
    </div>
  );
}
