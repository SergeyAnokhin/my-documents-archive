import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  Download, ChevronLeft, ChevronRight, FileText, Tag, RefreshCw, FlaskConical,
  ZoomIn, ZoomOut, Maximize, RotateCcw, RotateCw, X, Scissors, Check, Waypoints,
} from "lucide-react";
import type { Document } from "../../types";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";
import { useAdvancedMode } from "../../contexts/AdvancedModeContext";
import { reclassifyDocument, reindexDocument, updateTags, clearDocumentDate } from "../../api/documents";
import { TypePicker } from "./TypePicker";
import { useImageEdit } from "../../hooks/useImageEdit";
import { resolveImgSrc } from "./imgSrc";
import "./DocumentViewer.css";

interface Props {
  doc: Document | null;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
  isEmbedded?: boolean;
}

function formatDate(iso?: string) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}

// ── Main viewer ─────────────────────────────────────────────────────────────

export function DocumentViewer({ doc, onClose, onPrev, onNext, hasPrev, hasNext, isEmbedded }: Props) {
  const { t } = useT();
  const navigate = useNavigate();
  const { advancedMode } = useAdvancedMode();
  const [activeTab, setActiveTab] = useState<"preview" | "text" | "details" | "dev">("preview");
  const [devMsg, setDevMsg] = useState("");
  const [devLoading, setDevLoading] = useState<"reindex" | "reclassify" | null>(null);

  // Local type state so badge updates immediately after save
  const [localType, setLocalType] = useState<string | undefined>(undefined);
  const [localManual, setLocalManual] = useState<boolean | undefined>(undefined);
  const [localTags, setLocalTags] = useState<string[] | undefined>(undefined);
  const [localDate, setLocalDate] = useState<string | undefined | null>(undefined);

  // ── Zoom / Pan / Rotation ───────────────────────────────────────────────────
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const zoomRef = useRef(1);
  const panRef = useRef({ x: 0, y: 0 });
  const canvasRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const didAutoFitRef = useRef(false);
  const canvasPanStartRef = useRef<{ mouseX: number; mouseY: number; panX: number; panY: number } | null>(null);

  // ── Crop mode (lifted here so reset can be triggered on doc change) ─────────
  const [cropMode, setCropMode] = useState(false);

  // ── Keyboard shortcuts ────────────────────────────────────────────────────────
  const keyHandlerRef = useRef<(e: KeyboardEvent) => void>(() => {});
  useEffect(() => {
    const handler = (e: KeyboardEvent) => keyHandlerRef.current(e);
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // ── Image editing ────────────────────────────────────────────────────────────
  const armAutoFit = useCallback(() => { didAutoFitRef.current = false; }, []);
  const imageEdit = useImageEdit({
    docId: doc?.id ?? 0,
    isPdf: doc?.mime_type === "application/pdf" || false,
    zoomRef,
    imgRef,
    armAutoFit,
    cropMode,
    setCropMode,
    confirmMsg: t.lab.applyConfirm,
  });

  // Reset zoom/pan/rotation and local metadata when switching documents
  useEffect(() => {
    didAutoFitRef.current = false;
    zoomRef.current = 1;
    panRef.current = { x: 0, y: 0 };
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setCropMode(false);
    setLocalTags(undefined);
    setLocalDate(undefined);
  }, [doc?.id]);

  // Global pan tracking
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!canvasPanStartRef.current) return;
      const newPan = {
        x: canvasPanStartRef.current.panX + (e.clientX - canvasPanStartRef.current.mouseX),
        y: canvasPanStartRef.current.panY + (e.clientY - canvasPanStartRef.current.mouseY),
      };
      panRef.current = newPan;
      setPan(newPan);
    };
    const onUp = () => { canvasPanStartRef.current = null; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // Core zoom primitive
  const applyZoomAt = (factor: number, cx: number, cy: number) => {
    const prevZoom = zoomRef.current;
    const newZoom = Math.max(0.05, Math.min(20, prevZoom * factor));
    const ratio = newZoom / prevZoom;
    const newPan = {
      x: cx - (cx - panRef.current.x) * ratio,
      y: cy - (cy - panRef.current.y) * ratio,
    };
    zoomRef.current = newZoom;
    panRef.current = newPan;
    setZoom(newZoom);
    setPan(newPan);
  };

  // Mouse-wheel zoom toward cursor position
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      const rect = canvas.getBoundingClientRect();
      applyZoomAt(factor, e.clientX - rect.left, e.clientY - rect.top);
    };
    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, [doc?.id]);

  const displayType = localType !== undefined ? localType : doc?.document_type;
  const displayManual = localManual !== undefined ? localManual : doc?.manually_classified;
  const displayTags = localTags !== undefined ? localTags : (doc?.tags ?? []);
  const displayDate = localDate !== undefined ? localDate : doc?.document_date;

  const handleRemoveTag = async (tag: string) => {
    if (!doc) return;
    const next = displayTags.filter(t => t !== tag);
    setLocalTags(next);
    try { await updateTags(doc.id, next); } catch { setLocalTags(displayTags); }
  };

  const handleRemoveDate = async () => {
    if (!doc) return;
    setLocalDate(null);
    try {
      const updated = await clearDocumentDate(doc.id);
      setLocalDate(updated.document_date ?? null);
    } catch { setLocalDate(displayDate); }
  };

  const flashDev = (msg: string) => { setDevMsg(msg); setTimeout(() => setDevMsg(""), 4000); };

  const handleReindex = async () => {
    if (!doc) return;
    setDevLoading("reindex");
    try {
      await reindexDocument(doc.id);
      flashDev(t.reindexStarted);
    } catch {
      flashDev(t.error);
    } finally {
      setDevLoading(null);
    }
  };

  const handleReclassify = async () => {
    if (!doc) return;
    setDevLoading("reclassify");
    try {
      await reclassifyDocument(doc.id);
      flashDev(t.reclassifyStarted);
    } catch {
      flashDev(t.error);
    } finally {
      setDevLoading(null);
    }
  };

  const handleImgLoad = () => {
    if (didAutoFitRef.current) return;
    didAutoFitRef.current = true;
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || img.naturalWidth === 0) return;
    const cw = canvas.clientWidth;
    const ch = canvas.clientHeight;
    const fitZoom = Math.max(0.05, Math.min((cw - 24) / img.naturalWidth, (ch - 24) / img.naturalHeight));
    const fitPan = { x: (cw - img.naturalWidth * fitZoom) / 2, y: (ch - img.naturalHeight * fitZoom) / 2 };
    zoomRef.current = fitZoom;
    panRef.current = fitPan;
    setZoom(fitZoom);
    setPan(fitPan);
  };

  const handleZoomReset = () => {
    didAutoFitRef.current = false;
    handleImgLoad();
  };

  const zoomAround = (factor: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    applyZoomAt(factor, rect.width / 2, rect.height / 2);
  };

  const onCanvasMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0 || cropMode) return;
    canvasPanStartRef.current = { mouseX: e.clientX, mouseY: e.clientY, panX: pan.x, panY: pan.y };
    e.preventDefault();
  };

  if (!doc) return null;

  const isPdf = doc.mime_type === "application/pdf";
  const isImageMime = doc.mime_type?.startsWith("image/") ?? false;
  const vParam = doc.updated_at ? new Date(doc.updated_at).getTime() : "";
  const docUrl = `/api/documents/${doc.id}/download?inline=1${vParam ? `&v=${vParam}` : ""}`;
  const thumbUrl = doc.thumbnail_path
    ? `/thumbnails/${doc.thumbnail_path.split(/[/\\]/).pop()}${vParam ? `?v=${vParam}` : ""}`
    : null;

  // After apply, use imgVersion to bust the cache (updated_at may not have changed yet)
  const baseImgUrl = imageEdit.imgVersion > 0
    ? `/api/documents/${doc.id}/download?inline=1&ev=${imageEdit.imgVersion}`
    : docUrl;
  const rawImgSrc = isImageMime ? baseImgUrl : thumbUrl;
  // Show preview data when available (preview contains the transform applied to original)
  const imgSrc = resolveImgSrc(imageEdit.previewResult?.image_b64, rawImgSrc);

  const onImage = activeTab === "preview" && !isPdf && !!rawImgSrc;

  keyHandlerRef.current = (e: KeyboardEvent) => {
    if (!doc) return;
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (e.key === "ArrowLeft") { if (hasPrev) { e.preventDefault(); onPrev?.(); } }
    else if (e.key === "ArrowRight") { if (hasNext) { e.preventDefault(); onNext?.(); } }
    else if (onImage && (e.key === "+" || e.key === "=")) { e.preventDefault(); zoomAround(1.25); }
    else if (onImage && (e.key === "-" || e.key === "_")) { e.preventDefault(); zoomAround(1 / 1.25); }
    else if (onImage && e.key === " ") { e.preventDefault(); handleZoomReset(); }
    else if (onImage && e.key === "ArrowUp") { e.preventDefault(); imageEdit.setOutputRotation(r => (r - 90 + 360) % 360); }
    else if (onImage && e.key === "ArrowDown") { e.preventDefault(); imageEdit.setOutputRotation(r => (r + 90) % 360); }
    else if (onImage && (e.key === "c" || e.key === "C")) { e.preventDefault(); setCropMode(m => !m); if (cropMode) imageEdit.setCropRect(null); }
    else if (onImage && e.key === "1") { e.preventDefault(); imageEdit.setOutputScale(1); }
    else if (onImage && e.key === "2") { e.preventDefault(); imageEdit.setOutputScale(0.75); }
    else if (onImage && e.key === "3") { e.preventDefault(); imageEdit.setOutputScale(0.5); }
    else if (onImage && e.key === "4") { e.preventDefault(); imageEdit.setOutputScale(0.25); }
    else if (onImage && e.key === "5") { e.preventDefault(); imageEdit.setOutputScale(0.1); }
    else if (e.key === "Escape") {
      e.preventDefault();
      if (cropMode) { setCropMode(false); imageEdit.setCropRect(null); }
      else if (imageEdit.hasTransformChange || !!imageEdit.previewResult) { imageEdit.handleCancel(); }
      else { onClose(); }
    } else if (onImage && e.key === "Enter" && (imageEdit.hasTransformChange || !!imageEdit.previewResult) && !imageEdit.isApplying) {
      e.preventDefault();
      imageEdit.handleApply();
    }
  };

  const lab = t.lab;

  return (
    <Modal open={!!doc} onClose={onClose} size="xl" title={doc.filename}>
      <div className="viewer-layout">
        {/* Left — document */}
        <div className="viewer-preview">
          {/* Zoom toolbar (not shown for PDF — browser viewer has native zoom) */}
          {!isPdf && rawImgSrc && (
            <div className="viewer-zoom-toolbar">
              <button className="icon-btn" title="Zoom out" onClick={() => zoomAround(1 / 1.25)}>
                <ZoomOut size={14} />
              </button>
              <span className="viewer-zoom-pct">{Math.round(zoom * 100)}%</span>
              <button className="icon-btn" title="Zoom in" onClick={() => zoomAround(1.25)}>
                <ZoomIn size={14} />
              </button>
              <button className="icon-btn" title="Fit to screen" onClick={handleZoomReset}>
                <Maximize size={14} />
              </button>
              <span className="viewer-toolbar-sep" />
              <button
                className={`icon-btn${cropMode ? " viewer-btn-active" : ""}`}
                title={cropMode ? lab.cropClear : `${lab.cropTool} — ${lab.cropHint}`}
                onClick={() => { setCropMode(m => !m); if (cropMode) imageEdit.setCropRect(null); }}
              >
                <Scissors size={14} />
              </button>
              {imageEdit.imageInfo && (
                <span className="viewer-img-info text-xs text-muted">
                  {imageEdit.previewResult
                    ? `${imageEdit.previewResult.width}×${imageEdit.previewResult.height}`
                    : `${imageEdit.imageInfo.width}×${imageEdit.imageInfo.height}`}
                </span>
              )}
              {imageEdit.isPreviewing && (
                <span className="viewer-preview-badge viewer-preview-badge--loading">{lab.previewTag}</span>
              )}
              {imageEdit.previewResult && !imageEdit.isPreviewing && (
                <span className="viewer-preview-badge">{lab.previewTag}</span>
              )}
            </div>
          )}

          {/* Image editing toolbar — resize / quality / rotation / apply */}
          {!isPdf && rawImgSrc && imageEdit.imageInfo && (
            <div className="viewer-edit-toolbar">
              <span className="viewer-edit-label text-xs">{lab.resize}</span>
              <select
                className="viewer-edit-select"
                value={String(imageEdit.outputScale)}
                onChange={e => imageEdit.setOutputScale(Number(e.target.value))}
              >
                <option value="1">100% — {lab.original}</option>
                <option value="0.75">75%</option>
                <option value="0.5">50% — ÷2</option>
                <option value="0.25">25% — ÷4</option>
                <option value="0.1">10% — ÷10</option>
              </select>
              {imageEdit.imageInfo.can_adjust_quality && (
                <>
                  <span className="viewer-toolbar-sep" />
                  <span className="viewer-edit-label text-xs">{lab.quality}</span>
                  <input
                    type="range" min="10" max="95" step="5"
                    value={imageEdit.outputQuality}
                    onChange={e => imageEdit.setOutputQuality(Number(e.target.value))}
                    className="viewer-edit-slider"
                  />
                  <span className="text-xs" style={{ minWidth: 22, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {imageEdit.outputQuality}
                  </span>
                </>
              )}
              <span className="viewer-toolbar-sep" />
              <button
                className="icon-btn"
                title={lab.rotateLeft}
                onClick={() => imageEdit.setOutputRotation(r => (r - 90 + 360) % 360)}
              >
                <RotateCcw size={14} />
              </button>
              {imageEdit.outputRotation !== 0 && (
                <span className="text-xs text-muted" style={{ minWidth: 28, textAlign: "center" }}>
                  {imageEdit.outputRotation}°
                </span>
              )}
              <button
                className="icon-btn"
                title={lab.rotateRight}
                onClick={() => imageEdit.setOutputRotation(r => (r + 90) % 360)}
              >
                <RotateCw size={14} />
              </button>
              {cropMode && imageEdit.cropRect && imageEdit.cropRect.w > 0 && (
                <>
                  <span className="viewer-toolbar-sep" />
                  <span className="text-xs text-muted">
                    {lab.cropSelected}: {imageEdit.cropRect.w}×{imageEdit.cropRect.h}
                  </span>
                </>
              )}
              {(imageEdit.hasTransformChange || !!imageEdit.previewResult) && (
                <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                  <Button
                    variant="ghost" size="sm"
                    onClick={imageEdit.handleCancel}
                    disabled={imageEdit.isApplying}
                  >
                    {lab.cancelEdit}
                  </Button>
                  <Button
                    variant="primary" size="sm"
                    icon={<Check size={13} />}
                    loading={imageEdit.isApplying}
                    onClick={imageEdit.handleApply}
                  >
                    {imageEdit.applyDone ? lab.applyDone : lab.applyBtn}
                  </Button>
                </div>
              )}
            </div>
          )}

          {isPdf ? (
            <iframe src={docUrl} title={doc.filename} className="viewer-pdf" />
          ) : rawImgSrc ? (
            <div
              className="viewer-canvas"
              ref={canvasRef}
              onMouseDown={onCanvasMouseDown}
              style={{ cursor: cropMode ? "crosshair" : "grab" }}
            >
              <div
                className="viewer-img-wrapper"
                style={{
                  transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                  transformOrigin: "0 0",
                }}
              >
                <div style={{ position: "relative", display: "inline-block" }}>
                  <img
                    ref={imgRef}
                    src={imgSrc}
                    alt={doc.filename}
                    className="viewer-doc-img"
                    onLoad={handleImgLoad}
                    draggable={false}
                  />
                  {cropMode && !imageEdit.previewResult && (
                    <div
                      className="viewer-crop-overlay"
                      ref={imageEdit.cropOverlayRef}
                      onMouseDown={imageEdit.onCropOverlayMouseDown}
                    >
                      {imageEdit.cropRect && imageEdit.cropRect.w > 0 && imageEdit.cropRect.h > 0 && (
                        <div
                          className="viewer-crop-selection"
                          style={{
                            left: imageEdit.cropRect.x,
                            top: imageEdit.cropRect.y,
                            width: imageEdit.cropRect.w,
                            height: imageEdit.cropRect.h,
                          }}
                        >
                          <span className="viewer-crop-label">
                            {imageEdit.cropRect.w}×{imageEdit.cropRect.h}
                          </span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="viewer-thumb-placeholder">
              <FileText size={64} />
            </div>
          )}

          {/* Nav arrows */}
          <div className="viewer-nav">
            <button
              className="viewer-nav-btn"
              onClick={onPrev}
              disabled={!hasPrev}
              aria-label="Previous document"
            >
              <ChevronLeft size={20} />
            </button>
            <button
              className="viewer-nav-btn"
              onClick={onNext}
              disabled={!hasNext}
              aria-label="Next document"
            >
              <ChevronRight size={20} />
            </button>
          </div>
        </div>

        {/* Right — info */}
        <div className="viewer-info">
          {/* Tabs */}
          <div className="viewer-tabs">
            {(["preview", "text", "details", "dev"] as const).map((tab) => (
              <button
                key={tab}
                className={`viewer-tab${activeTab === tab ? " active" : ""}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab === "preview" ? "Preview"
                  : tab === "text" ? t.recognizedText
                  : tab === "details" ? t.metadata
                  : t.devMode}
              </button>
            ))}
          </div>

          <div className="viewer-tab-body">
            {activeTab === "preview" && (
              <div className="viewer-meta-list">
                {doc.summary && <p className="viewer-summary">{doc.summary}</p>}

                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">Type</span>
                  <TypePicker
                    docId={doc.id}
                    currentType={displayType}
                    isManual={displayManual}
                    onSaved={(t) => { setLocalType(t); setLocalManual(true); }}
                  />
                </div>

                {displayTags.length > 0 && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label"><Tag size={13}/> Tags</span>
                    <div className="viewer-tags">
                      {displayTags.map((tag) => (
                        <span key={tag} className="tag">
                          {tag}
                          <button className="tag-remove" onClick={() => handleRemoveTag(tag)} title="Remove tag">
                            <X size={10} />
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {doc.language && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Language</span>
                    <span>{doc.language}</span>
                  </div>
                )}
                {doc.organization && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Organization</span>
                    <span>{doc.organization}</span>
                  </div>
                )}
                {(doc.person_first_name || doc.person_last_name) && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Person</span>
                    <span>{[doc.person_first_name, doc.person_last_name].filter(Boolean).join(" ")}</span>
                  </div>
                )}
                {displayDate && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Date</span>
                    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      {formatDate(displayDate)}
                      <button className="tag-remove" onClick={handleRemoveDate} title="Remove date">
                        <X size={10} />
                      </button>
                    </span>
                  </div>
                )}
                {doc.amount != null && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Amount</span>
                    <span>{doc.amount} {doc.amount_currency ?? ""}</span>
                  </div>
                )}
              </div>
            )}

            {activeTab === "text" && (
              <div className="viewer-ocr-text text-sm">
                {doc.vision_description && (
                  <div style={{ marginBottom: 16 }}>
                    <p className="text-xs text-muted" style={{ marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      AI Vision
                    </p>
                    <p style={{ lineHeight: 1.6 }}>{doc.vision_description}</p>
                    <hr style={{ margin: "12px 0", borderColor: "var(--color-border)" }} />
                  </div>
                )}
                <p className="text-xs text-muted" style={{ marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  OCR
                </p>
                <div className="text-mono">
                  {doc.ocr_text || <em className="text-muted">{t.noSummary}</em>}
                </div>
              </div>
            )}

            {activeTab === "details" && (
              <div className="viewer-meta-list">
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">Filename</span>
                  <span className="text-mono text-sm">{doc.filename}</span>
                </div>
                {doc.document_date && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Document date</span>
                    <span>{formatDate(doc.document_date)}</span>
                  </div>
                )}
                {doc.added_at && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Added</span>
                    <span>{formatDate(doc.added_at)}</span>
                  </div>
                )}
                {doc.file_size && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Size</span>
                    <span>{(doc.file_size / 1024).toFixed(1)} KB</span>
                  </div>
                )}
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">OCR</span>
                  <span className={`status-dot ${doc.ocr_status}`} style={{ marginRight: 6 }} />
                  <span className="text-sm">{t.status[doc.ocr_status as keyof typeof t.status]}</span>
                </div>
              </div>
            )}

            {activeTab === "dev" && (
              <div className="viewer-meta-list">
                <p className="text-xs text-muted" style={{ marginBottom: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {t.pipelineStatus}
                </p>

                {/* OCR */}
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">OCR</span>
                  <span className={`status-dot ${doc.ocr_status}`} style={{ marginRight: 6 }} />
                  <span className="text-sm">{doc.ocr_status}</span>
                </div>
                {doc.ocr_error && (
                  <p className="text-xs" style={{ color: "var(--color-error, #c0392b)", marginBottom: 8, marginLeft: 8 }}>
                    {doc.ocr_error}
                  </p>
                )}

                {/* Vision */}
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">Vision</span>
                  <span className={`status-dot ${doc.vision_status}`} style={{ marginRight: 6 }} />
                  <span className="text-sm">{doc.vision_status}</span>
                </div>
                {doc.vision_error && (
                  <p className="text-xs" style={{ color: "var(--color-error, #c0392b)", marginBottom: 8, marginLeft: 8 }}>
                    {doc.vision_error}
                  </p>
                )}

                {/* Analysis */}
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">Analysis</span>
                  <span className={`status-dot ${doc.analysis_status}`} style={{ marginRight: 6 }} />
                  <span className="text-sm">{doc.analysis_status}</span>
                </div>
                {doc.analysis_error && (
                  <p className="text-xs" style={{ color: "var(--color-error, #c0392b)", marginBottom: 8, marginLeft: 8 }}>
                    {doc.analysis_error}
                  </p>
                )}

                {/* Embedding status */}
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">Embedding</span>
                  {isEmbedded === undefined ? (
                    <span className="text-sm text-muted">—</span>
                  ) : isEmbedded ? (
                    <span className="text-sm" style={{ color: "#0d9488", display: "flex", alignItems: "center", gap: 4 }}>
                      <Waypoints size={13} /> indexed
                    </span>
                  ) : (
                    <span className="text-sm text-muted">not indexed</span>
                  )}
                </div>

                {/* OCR model attribution */}
                {doc.ocr_model && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">{t.lab.ocrModel}</span>
                    <span className="text-sm text-mono">{doc.ocr_model}</span>
                  </div>
                )}

                {/* Classification info */}
                {doc.classification_source && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Classification</span>
                    <span className="text-sm text-muted">
                      {doc.classification_source}
                      {doc.classification_confidence != null && (
                        <> · {Math.round(doc.classification_confidence * 100)}% conf</>
                      )}
                    </span>
                  </div>
                )}

                {/* Costs */}
                {((doc.api_cost_vision ?? 0) > 0 || (doc.api_cost_analysis ?? 0) > 0) && (
                  <div className="viewer-meta-row" style={{ marginTop: 8 }}>
                    <span className="viewer-meta-label">API cost</span>
                    <span className="text-xs text-muted">
                      vision ${(doc.api_cost_vision ?? 0).toFixed(5)} · analysis ${(doc.api_cost_analysis ?? 0).toFixed(5)}
                    </span>
                  </div>
                )}

                {/* Actions */}
                <div style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RefreshCw size={13} />}
                    loading={devLoading === "reclassify"}
                    onClick={handleReclassify}
                  >
                    {t.reclassify}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RefreshCw size={13} />}
                    loading={devLoading === "reindex"}
                    onClick={handleReindex}
                  >
                    {t.reindex}
                  </Button>
                </div>
                {devMsg && <p className="text-xs text-muted" style={{ marginTop: 8 }}>{devMsg}</p>}
              </div>
            )}
          </div>

          {/* Download */}
          <div className="viewer-actions">
            {advancedMode && (
              <Button
                variant="primary"
                size="sm"
                icon={<FlaskConical size={14} />}
                onClick={() => navigate(`/lab/${doc.id}`)}
              >
                {t.labMode}
              </Button>
            )}
            <a href={`/api/documents/${doc.id}/download`} download>
              <Button variant="secondary" size="sm" icon={<Download size={14} />}>
                {t.download}
              </Button>
            </a>
          </div>
        </div>
      </div>
    </Modal>
  );
}
