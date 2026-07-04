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
  runLabOcr, runLabVision, runLabTextAnalysis, runLabJudge, saveLabResult,
} from "../api/documents";
import type { Document, AIProvider, LabMethods, LabResult, LabJudgeResult } from "../types";
import { formatMs, formatFileSize, uid } from "./lab/labUtils";
import { useLogs } from "./lab/useLogs";
import { usePanelResize } from "./lab/usePanelResize";
import { useImageTransform } from "./lab/useImageTransform";
import { useImageEdit } from "../hooks/useImageEdit";
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

  // ── Crop mode (lifted here so it can be passed to both useImageTransform and useImageEdit) ──
  const [cropMode, setCropMode] = useState(false);

  // ── Zoom / Pan ─────────────────────────────────────────────────────────────────
  const isPdf = doc?.mime_type === "application/pdf" || !!doc?.filename.toLowerCase().endsWith(".pdf");
  const {
    zoom, pan, zoomRef, zoomAround, handleImgLoad, handleZoomReset, armAutoFit, onCanvasMouseDown,
  } = useImageTransform({ canvasRef, imgRef, cropMode, isPdf, resetKey: id });

  // ── Image editing (resize / quality / rotation / crop / preview / apply) ──────
  const { logs, showLogs, setShowLogs, addLog, clearLogs, logsEndRef } = useLogs();

  const imageEdit = useImageEdit({
    docId, isPdf, zoomRef, imgRef, armAutoFit,
    cropMode, setCropMode,
    onLog: addLog,
  });

  // ── Panel resize ─────────────────────────────────────────────────────────────
  const { panelWidth, onResizerDown } = usePanelResize();

  // ── Keyboard listener — stable registration, handler ref updated every render ─
  const keyHandlerRef = useRef<(e: KeyboardEvent) => void>(() => {});
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

  // ── Modal drag global handlers ────────────────────────────────────────────────
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!modalDragStart.current) return;
      const dx = e.clientX - modalDragStart.current.mx;
      const dy = e.clientY - modalDragStart.current.my;
      setModalPos({
        x: Math.max(0, modalDragStart.current.px + dx),
        y: Math.max(0, modalDragStart.current.py + dy),
      });
    };
    const onUp = () => { modalDragStart.current = null; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // ── Data loading ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!docId) return;
    getDocument(docId).then(setDoc).catch(() => {});
    getLabMethods().then(setMethods).catch(() => {});
    listProviders().then(setProviders).catch(() => {});
  }, [docId]);

  const visionProviders = useMemo(
    () => providers.filter(
      p => p.enabled
        && (p.task_type === "vision" || p.task_type === "both")
        && p.capabilities?.vision,
    ),
    [providers],
  );

  const textAnalysisProviders = useMemo(
    () => providers.filter(p => p.enabled && p.capabilities?.text && p.capabilities?.analysis),
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

  const handleFieldRemove = (resultId: string, fieldKey: string) => {
    const keyMap: Record<string, string[]> = {
      type: ["document_type"],
      date: ["document_date"],
      person: ["person_first_name", "person_last_name"],
      org: ["organization"],
      amount: ["amount", "amount_currency"],
      lang: ["language"],
      tags: ["tags"],
    };
    setResults(prev => prev.map(r => {
      if (r.id !== resultId || !r.fields) return r;
      const next = { ...r.fields };
      for (const k of keyMap[fieldKey] ?? [fieldKey]) delete (next as Record<string, unknown>)[k];
      return { ...r, fields: next };
    }));
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

  const handleTextAnalysis = async (p: AIProvider) => {
    const sourceText = results[results.length - 1]?.text || doc?.ocr_text || "";
    if (!sourceText.trim()) return;
    setRunningVision(prev => new Set(prev).add(p.id));
    addLog(`→ Text analysis [${p.name}]`);
    try {
      const res = await runLabTextAnalysis(docId, p.id, sourceText);
      upsert({
        id: uid(), kind: "vision", label: `${p.name} · text`, providerId: p.id,
        providerModel: res.model_name || p.model || undefined,
        text: sourceText, ms: res.ms, cost: res.cost,
        tokens_in: res.tokens_in, tokens_out: res.tokens_out,
        fields: res.fields || undefined,
      });
      addLog(`← Text analysis [${p.name}]: ${formatMs(res.ms)}`, "ok");
    } catch (e) {
      addLog(`✕ Text analysis [${p.name}]: ${(e as Error).message}`, "err");
    } finally {
      setRunningVision(prev => { const next = new Set(prev); next.delete(p.id); return next; });
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
      const hasVision = provider.capabilities?.vision ?? false;
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

  // Update keyboard handler every render so it always closes over fresh state
  keyHandlerRef.current = (e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (e.key === "+" || e.key === "=") { e.preventDefault(); zoomAround(1.25); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomAround(1 / 1.25); }
    else if (e.key === " ") { e.preventDefault(); handleZoomReset(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); imageEdit.setOutputRotation(r => (r - 90 + 360) % 360); }
    else if (e.key === "ArrowDown") { e.preventDefault(); imageEdit.setOutputRotation(r => (r + 90) % 360); }
    else if (!isPdf && (e.key === "c" || e.key === "C")) { e.preventDefault(); setCropMode(m => !m); if (cropMode) imageEdit.setCropRect(null); }
    else if (!isPdf && e.key === "1") { e.preventDefault(); imageEdit.setOutputScale(1); }
    else if (!isPdf && e.key === "2") { e.preventDefault(); imageEdit.setOutputScale(0.75); }
    else if (!isPdf && e.key === "3") { e.preventDefault(); imageEdit.setOutputScale(0.5); }
    else if (!isPdf && e.key === "4") { e.preventDefault(); imageEdit.setOutputScale(0.25); }
    else if (!isPdf && e.key === "5") { e.preventDefault(); imageEdit.setOutputScale(0.1); }
    else if (e.key === "Escape") {
      e.preventDefault();
      if (cropMode) { setCropMode(false); imageEdit.setCropRect(null); }
      else if (imageEdit.hasTransformChange || !!imageEdit.previewResult) { imageEdit.handleCancel(); }
      else { navigate("/"); }
    } else if (e.key === "Enter" && (imageEdit.hasTransformChange || !!imageEdit.previewResult) && !imageEdit.isApplying) {
      e.preventDefault();
      imageEdit.handleApply();
    }
  };

  const downloadUrl = `/api/documents/${docId}/download?inline=1`;
  const imgSrc = imageEdit.previewResult
    ? `data:image/jpeg;base64,${imageEdit.previewResult.image_b64}`
    : `${downloadUrl}&v=${imageEdit.imgVersion}`;

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
                  onClick={() => { setCropMode(m => !m); if (cropMode) imageEdit.setCropRect(null); }}
                >
                  <Scissors size={16} />
                </button>
              </>
            )}
            {imageEdit.imageInfo && (
              <span className="lab-img-info text-xs text-muted">
                {imageEdit.previewResult
                  ? `${imageEdit.previewResult.width}×${imageEdit.previewResult.height} · ${formatFileSize(imageEdit.previewResult.file_size)}`
                  : `${imageEdit.imageInfo.width}×${imageEdit.imageInfo.height} · ${formatFileSize(imageEdit.imageInfo.file_size)}`
                }
              </span>
            )}
            {imageEdit.isPreviewing && (
              <span className="lab-preview-badge lab-preview-badge--loading">{lab.previewTag}</span>
            )}
            {imageEdit.previewResult && !imageEdit.isPreviewing && (
              <span className="lab-preview-badge">{lab.previewTag}</span>
            )}
          </div>

          {!isPdf && (
            <div className="lab-doc-toolbar2">
              <span className="lab-tool2-label text-xs">{lab.resize}</span>
              <select
                className="lab-select2"
                value={String(imageEdit.outputScale)}
                onChange={e => imageEdit.setOutputScale(Number(e.target.value))}
              >
                <option value="1">100% — {lab.original}</option>
                <option value="0.75">75%</option>
                <option value="0.5">50% — ÷2</option>
                <option value="0.25">25% — ÷4</option>
                <option value="0.1">10% — ÷10</option>
              </select>
              {imageEdit.imageInfo?.can_adjust_quality && (
                <>
                  <div className="lab-toolbar-sep" />
                  <span className="lab-tool2-label text-xs">{lab.quality}</span>
                  <input
                    type="range" min="10" max="95" step="5"
                    value={imageEdit.outputQuality}
                    onChange={e => imageEdit.setOutputQuality(Number(e.target.value))}
                    className="lab-slider2"
                  />
                  <span className="text-xs" style={{ minWidth: 22, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {imageEdit.outputQuality}
                  </span>
                </>
              )}
              <div className="lab-toolbar-sep" />
              <button
                className="icon-btn"
                title={`${lab.rotateLeft} (←)`}
                onClick={() => imageEdit.setOutputRotation(r => (r - 90 + 360) % 360)}
              >
                <RotateCcw size={15} />
              </button>
              {imageEdit.outputRotation !== 0 && (
                <span className="text-xs text-muted" style={{ minWidth: 30, textAlign: "center" }}>
                  {imageEdit.outputRotation}°
                </span>
              )}
              <button
                className="icon-btn"
                title={`${lab.rotateRight} (→)`}
                onClick={() => imageEdit.setOutputRotation(r => (r + 90) % 360)}
              >
                <RotateCw size={15} />
              </button>
              {cropMode && imageEdit.cropRect && imageEdit.cropRect.w > 0 && (
                <>
                  <div className="lab-toolbar-sep" />
                  <span className="text-xs text-muted">
                    {lab.cropSelected}: {imageEdit.cropRect.w}×{imageEdit.cropRect.h}
                  </span>
                </>
              )}
              {(imageEdit.hasTransformChange || !!imageEdit.previewResult) && (
                <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                  <Button
                    variant="ghost" size="sm"
                    title={`${lab.cancelEdit} (Esc)`}
                    onClick={imageEdit.handleCancel}
                    disabled={imageEdit.isApplying}
                  >
                    {lab.cancelEdit}
                  </Button>
                  <Button
                    variant="primary" size="sm"
                    icon={<Check size={13} />}
                    loading={imageEdit.isApplying}
                    title={`${imageEdit.applyDone ? lab.applyDone : lab.applyBtn} (Enter)`}
                    onClick={imageEdit.handleApply}
                  >
                    {imageEdit.applyDone ? lab.applyDone : lab.applyBtn}
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
                  {cropMode && !imageEdit.previewResult && (
                    <div
                      className="lab-crop-overlay"
                      ref={imageEdit.cropOverlayRef}
                      onMouseDown={imageEdit.onCropOverlayMouseDown}
                    >
                      {imageEdit.cropRect && imageEdit.cropRect.w > 0 && imageEdit.cropRect.h > 0 && (
                        <div
                          className="lab-crop-selection"
                          style={{
                            left: imageEdit.cropRect.x,
                            top: imageEdit.cropRect.y,
                            width: imageEdit.cropRect.w,
                            height: imageEdit.cropRect.h,
                          }}
                        >
                          <span className="lab-crop-label">
                            {imageEdit.cropRect.w}×{imageEdit.cropRect.h}
                          </span>
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

          <section className="lab-section">
            <h3 className="lab-section-title">{lab.textAnalysis}</h3>
            <p className="text-xs text-muted" style={{ marginBottom: 6 }}>{lab.textAnalysisHint}</p>
            <div className="lab-provider-list">
              {textAnalysisProviders.map(p => (
                <div key={p.id} className="lab-provider-row">
                  <span className="lab-provider-name">{p.name}</span>
                  <Button
                    variant="secondary" size="sm" icon={<Play size={13} />}
                    loading={runningVision.has(p.id)}
                    disabled={!((results[results.length - 1]?.text || doc?.ocr_text || "").trim())}
                    onClick={() => handleTextAnalysis(p)}
                  >
                    {lab.run}
                  </Button>
                </div>
              ))}
            </div>
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
              onFieldRemove={handleFieldRemove}
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
