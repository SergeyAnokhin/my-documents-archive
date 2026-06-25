import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, ZoomIn, ZoomOut, Maximize, Maximize2, Play, X, Scale, Trophy,
  Terminal, Save, Scissors, Eye, Check,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { useT } from "../i18n";
import {
  getDocument, getLabMethods, listProviders,
  runLabOcr, runLabVision, runLabJudge, saveLabResult,
  getLabImageInfo, previewLabTransform, applyLabTransform,
} from "../api/documents";
import type {
  Document, AIProvider, LabMethods, LabResult, LabJudgeResult, ExtractedFields,
  LabImageInfo, LabPreviewResult, LabTransformParams,
} from "../types";
import "./LabPage.css";

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)} s`;
  const min = Math.floor(ms / 60000);
  const sec = Math.round((ms % 60000) / 1000);
  return `${min} min ${sec} s`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function FieldChips({ fields }: { fields: ExtractedFields }) {
  const chips: { key: string; value: string }[] = [];
  if (fields.document_type) chips.push({ key: "type", value: fields.document_type.replace(/_/g, " ") });
  if (fields.document_date) chips.push({ key: "date", value: fields.document_date });
  const name = [fields.person_first_name, fields.person_last_name].filter(Boolean).join(" ");
  if (name) chips.push({ key: "person", value: name });
  if (fields.organization) chips.push({ key: "org", value: fields.organization });
  if (fields.amount != null) {
    const amt = fields.amount_currency ? `${fields.amount} ${fields.amount_currency}` : String(fields.amount);
    chips.push({ key: "amount", value: amt });
  }
  if (fields.language) chips.push({ key: "lang", value: fields.language });
  if (chips.length === 0) return null;
  return (
    <div className="lab-field-chips">
      {chips.map(c => (
        <span key={c.key} className={`lab-field-chip lab-field-chip--${c.key}`} title={c.key}>
          {c.value}
        </span>
      ))}
    </div>
  );
}

const VISION_CAPABLE = ["anthropic", "openai", "gemini", "openrouter", "mistral"];

function uid() {
  return Math.random().toString(36).slice(2);
}

interface LogLine {
  id: string;
  ts: string;
  msg: string;
  kind: "info" | "ok" | "err";
}

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

  const [runningOcr, setRunningOcr] = useState<string | null>(null);
  const [runningVision, setRunningVision] = useState<number | null>(null);

  // Judge
  const [judgeProviders, setJudgeProviders] = useState<number[]>([]);
  const [judgingIds, setJudgingIds] = useState<number[]>([]);
  const [judgeResults, setJudgeResults] = useState<Record<number, LabJudgeResult>>({});
  const [judgeErrors, setJudgeErrors] = useState<Record<number, string>>({});

  const [savingId, setSavingId] = useState<string | null>(null);
  const [savedId, setSavedId] = useState<string | null>(null);

  // ── Zoom / Pan ──────────────────────────────────────────────────────────────
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const zoomRef = useRef(zoom);
  useEffect(() => { zoomRef.current = zoom; }, [zoom]);

  const canvasRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const didAutoFitRef = useRef(false);
  const canvasPanStartRef = useRef<{ mouseX: number; mouseY: number; panX: number; panY: number } | null>(null);

  // ── Image tools ──────────────────────────────────────────────────────────────
  const [imageInfo, setImageInfo] = useState<LabImageInfo | null>(null);
  const [outputScale, setOutputScale] = useState<number>(1);
  const [outputQuality, setOutputQuality] = useState<number>(85);
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

  // ── Panel resize ─────────────────────────────────────────────────────────────
  const [panelWidth, setPanelWidth] = useState(() => {
    try {
      const v = localStorage.getItem("lab-panel-width");
      if (v) return Math.max(300, Math.min(900, Number(v)));
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

  // ── Floating text modal ──────────────────────────────────────────────────────
  const [expandedResult, setExpandedResult] = useState<LabResult | null>(null);
  const [modalPos, setModalPos] = useState({ x: 24, y: 80 });
  const modalDragStart = useRef<{ mx: number; my: number; px: number; py: number } | null>(null);

  const onModalDragStart = (e: React.MouseEvent, curPos: { x: number; y: number }) => {
    modalDragStart.current = { mx: e.clientX, my: e.clientY, px: curPos.x, py: curPos.y };
    e.preventDefault();
  };

  // ── Global mouse handlers ────────────────────────────────────────────────────
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (isResizing.current) {
        const dx = resizeStartX.current - e.clientX;
        setPanelWidth(Math.max(300, Math.min(900, resizeStartWidth.current + dx)));
      }
      if (modalDragStart.current) {
        const dx = e.clientX - modalDragStart.current.mx;
        const dy = e.clientY - modalDragStart.current.my;
        setModalPos({
          x: Math.max(0, modalDragStart.current.px + dx),
          y: Math.max(0, modalDragStart.current.py + dy),
        });
      }
      if (canvasPanStartRef.current) {
        const dx = e.clientX - canvasPanStartRef.current.mouseX;
        const dy = e.clientY - canvasPanStartRef.current.mouseY;
        setPan({
          x: canvasPanStartRef.current.panX + dx,
          y: canvasPanStartRef.current.panY + dy,
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
      if (isResizing.current) {
        try { localStorage.setItem("lab-panel-width", String(panelWidthRef.current)); } catch {}
      }
      isResizing.current = false;
      modalDragStart.current = null;
      if (canvasPanStartRef.current && canvasRef.current) {
        delete canvasRef.current.dataset.panning;
      }
      canvasPanStartRef.current = null;
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

  // ── Mouse wheel zoom at cursor ────────────────────────────────────────────────
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
  }, []);

  // ── Logs ─────────────────────────────────────────────────────────────────────
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);

  const addLog = (msg: string, kind: LogLine["kind"] = "info") => {
    const ts = new Date().toLocaleTimeString("ru-RU", { hour12: false });
    setLogs(prev => [...prev, { id: uid(), ts, msg, kind }]);
  };

  useEffect(() => {
    if (showLogs) logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, showLogs]);

  // ── Data loading ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!docId) return;
    didAutoFitRef.current = false;
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

  // ── Zoom helpers ──────────────────────────────────────────────────────────────
  const zoomAround = (factor: number) => {
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
  };

  const handleImgLoad = () => {
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
  };

  const handleZoomReset = () => {
    didAutoFitRef.current = false;
    handleImgLoad();
  };

  // ── Canvas pan mousedown ──────────────────────────────────────────────────────
  const onCanvasMouseDown = (e: React.MouseEvent) => {
    if (cropMode || isPdf || e.button !== 0) return;
    canvasPanStartRef.current = { mouseX: e.clientX, mouseY: e.clientY, panX: pan.x, panY: pan.y };
    if (canvasRef.current) canvasRef.current.dataset.panning = "true";
    e.preventDefault();
  };

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
    setRunningOcr(method);
    addLog(`→ OCR [${method}]`);
    try {
      const res = await runLabOcr(docId, method);
      upsert({ id: uid(), kind: "ocr", label: method, text: res.text, ms: res.ms, fields: res.fields || undefined });
      addLog(`← OCR [${method}]: ${res.text.length} chars · ${formatMs(res.ms)}`, "ok");
    } catch (e) {
      upsert({ id: uid(), kind: "ocr", label: method, text: `⚠️ ${lab.failed}: ${(e as Error).message}`, ms: 0 });
      addLog(`✗ OCR [${method}]: ${(e as Error).message}`, "err");
    } finally {
      setRunningOcr(null);
    }
  };

  const handleVision = async (p: AIProvider) => {
    setRunningVision(p.id);
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
      setRunningVision(null);
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

  // ── Image transform handlers ──────────────────────────────────────────────────
  const handlePreview = async () => {
    setIsPreviewing(true);
    try {
      const params: LabTransformParams = {};
      if (outputScale !== 1) params.scale = outputScale;
      if (cropRect) params.crop = cropRect;
      if (imageInfo?.can_adjust_quality && outputQuality !== 85) params.quality = outputQuality;
      const result = await previewLabTransform(docId, params);
      setPreviewResult(result);
      addLog(`→ Preview: ${result.width}×${result.height} · ${formatFileSize(result.file_size)}`, "ok");
    } catch (e) {
      addLog(`✗ Preview: ${(e as Error).message}`, "err");
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleApply = async () => {
    if (!window.confirm(lab.applyConfirm)) return;
    setIsApplying(true);
    try {
      const params: LabTransformParams = {};
      if (outputScale !== 1) params.scale = outputScale;
      if (cropRect) params.crop = cropRect;
      if (imageInfo?.can_adjust_quality && outputQuality !== 85) params.quality = outputQuality;
      const result = await applyLabTransform(docId, params);
      setImageInfo(prev => prev ? { ...prev, width: result.width, height: result.height, file_size: result.file_size } : prev);
      setPreviewResult(null);
      setOutputScale(1);
      setOutputQuality(85);
      setCropRect(null);
      setCropMode(false);
      setApplyDone(true);
      setImgVersion(v => v + 1);
      addLog(`✓ Applied: ${result.width}×${result.height} · ${formatFileSize(result.file_size)}`, "ok");
      setTimeout(() => setApplyDone(false), 2500);
    } catch (e) {
      addLog(`✗ Apply: ${(e as Error).message}`, "err");
    } finally {
      setIsApplying(false);
    }
  };

  const handleDiscardPreview = () => {
    setPreviewResult(null);
  };

  const isPdf = doc?.mime_type === "application/pdf" || doc?.filename.toLowerCase().endsWith(".pdf");
  const downloadUrl = `/api/documents/${docId}/download?inline=1`;
  const imgSrc = previewResult
    ? `data:image/jpeg;base64,${previewResult.image_b64}`
    : `${downloadUrl}&v=${imgVersion}`;

  const hasTransformChange = outputScale !== 1 || !!cropRect || (imageInfo?.can_adjust_quality && outputQuality !== 85);

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
            <button className="icon-btn" title={lab.zoomOut} onClick={() => zoomAround(1 / 1.25)}>
              <ZoomOut size={16} />
            </button>
            <span className="text-xs text-muted" style={{ minWidth: 42, textAlign: "center" }}>
              {Math.round(zoom * 100)}%
            </span>
            <button className="icon-btn" title={lab.zoomIn} onClick={() => zoomAround(1.25)}>
              <ZoomIn size={16} />
            </button>
            <button className="icon-btn" title={lab.resetZoom} onClick={handleZoomReset}>
              <Maximize size={16} />
            </button>
            {!isPdf && (
              <>
                <div className="lab-toolbar-sep" />
                <button
                  className={`icon-btn${cropMode ? " active" : ""}`}
                  title={cropMode ? lab.cropClear : lab.cropTool}
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
            {previewResult && (
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
                disabled={!!previewResult}
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
                    disabled={!!previewResult}
                    className="lab-slider2"
                  />
                  <span className="text-xs" style={{ minWidth: 22, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{outputQuality}</span>
                </>
              )}
              {cropMode && cropRect && cropRect.w > 0 && (
                <>
                  <div className="lab-toolbar-sep" />
                  <span className="text-xs text-muted">{lab.cropSelected}: {cropRect.w}×{cropRect.h}</span>
                </>
              )}
              <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                {previewResult ? (
                  <>
                    <Button
                      variant="primary" size="sm"
                      icon={<Check size={13} />}
                      loading={isApplying}
                      onClick={handleApply}
                    >
                      {applyDone ? lab.applyDone : lab.applyBtn}
                    </Button>
                    <Button variant="secondary" size="sm" onClick={handleDiscardPreview}>
                      {lab.discardPreview}
                    </Button>
                  </>
                ) : (
                  <Button
                    variant="secondary" size="sm"
                    icon={<Eye size={13} />}
                    loading={isPreviewing}
                    disabled={!hasTransformChange}
                    onClick={handlePreview}
                  >
                    {lab.previewBtn}
                  </Button>
                )}
              </div>
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
                <button className="lab-logs-clear" onClick={() => setLogs([])}>{lab.clearLogs}</button>
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
                  loading={runningOcr === m}
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
                      loading={runningVision === p.id}
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
            {results.length === 0 ? (
              <p className="text-xs text-muted">{lab.emptyResults}</p>
            ) : (
              <div className="lab-results">
                {results.map(r => {
                  const isBest = bestLabels.has(r.label);
                  const isSaving = savingId === r.id;
                  const isSaved = savedId === r.id;
                  return (
                    <div key={r.id} className={`lab-card${isBest ? " best" : ""}`}>
                      <div className="lab-card-head">
                        <span className={`lab-kind ${r.kind}`}>{r.kind === "ocr" ? "OCR" : "AI"}</span>
                        <span className="lab-card-label">{r.label}</span>
                        {isBest && <Trophy size={13} className="lab-best-icon" />}
                        <span className="lab-card-meta">
                          {r.text.length} {lab.chars} · {formatMs(r.ms)}
                          {(r.tokens_in != null && r.tokens_in > 0) ? ` · ${r.tokens_in}↑${r.tokens_out}↓ tok` : ""}
                          {r.cost != null && r.cost > 0 ? ` · $${r.cost.toFixed(5)}` : ""}
                        </span>
                        <button
                          className={`icon-btn lab-save-btn${isSaved ? " saved" : ""}`}
                          title={isSaved ? lab.saved : lab.saveResult}
                          disabled={isSaving}
                          onClick={() => handleSave(r)}
                        >
                          <Save size={13} />
                        </button>
                        <button className="icon-btn" title={lab.expand}
                          onClick={() => { setExpandedResult(r); setModalPos({ x: 24, y: 80 }); }}>
                          <Maximize2 size={13} />
                        </button>
                        <button className="icon-btn" title={lab.remove}
                          onClick={() => setResults(prev => prev.filter(x => x.id !== r.id))}>
                          <X size={13} />
                        </button>
                      </div>
                      {r.fields && Object.keys(r.fields).length > 0 && (
                        <FieldChips fields={r.fields} />
                      )}
                      <pre className="lab-card-text">{r.text || "—"}</pre>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* Judge */}
          <section className="lab-section">
            <h3 className="lab-section-title"><Scale size={14} /> {lab.judge}</h3>
            {premiumProviders.length === 0 ? (
              <p className="text-xs text-muted">{lab.noPremium}</p>
            ) : (
              <>
                <p className="text-xs text-muted" style={{ marginBottom: 8 }}>{lab.judgeHint}</p>
                <div className="lab-judge-list">
                  {premiumProviders.map(p => {
                    const hasVision = VISION_CAPABLE.includes(p.provider_type);
                    const isChecked = judgeProviders.includes(p.id);
                    const isRunning = judgingIds.includes(p.id);
                    return (
                      <label key={p.id} className="lab-judge-item">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={e => setJudgeProviders(prev =>
                            e.target.checked ? [...prev, p.id] : prev.filter(id => id !== p.id),
                          )}
                        />
                        <span className={`lab-capability-badge ${hasVision ? "vision" : "text"}`}>
                          {hasVision ? t.admin.ai.visionBadge : lab.textBadge}
                        </span>
                        <span className="lab-judge-name">{p.name}</span>
                        {isRunning && <span className="lab-judge-running">…</span>}
                      </label>
                    );
                  })}
                </div>

                <Button
                  variant="primary" size="sm"
                  icon={<Scale size={14} />}
                  loading={judgingIds.length > 0}
                  disabled={results.length < 2 || judgeProviders.length === 0}
                  onClick={handleJudge}
                  style={{ marginTop: 8 }}
                >
                  {judgingIds.length > 0 ? lab.comparing : lab.compare}
                </Button>
                {results.length < 2 && <p className="text-xs text-muted" style={{ marginTop: 6 }}>{lab.needTwo}</p>}

                {premiumProviders
                  .filter(p => judgeResults[p.id] || judgeErrors[p.id])
                  .map(p => {
                    const result = judgeResults[p.id];
                    const error = judgeErrors[p.id];
                    const hasVision = VISION_CAPABLE.includes(p.provider_type);
                    return (
                      <div key={p.id}>
                        <div className="lab-verdict-judge-header">
                          <span className={`lab-capability-badge ${hasVision ? "vision" : "text"}`}>
                            {hasVision ? t.admin.ai.visionBadge : lab.textBadge}
                          </span>
                          <span>{p.name}</span>
                        </div>
                        {error && (
                          <p className="text-xs" style={{ color: "var(--color-error)", marginTop: 4 }}>{error}</p>
                        )}
                        {result && (
                          <div className="lab-verdict">
                            <div className="lab-verdict-best">
                              <Trophy size={15} /> {lab.best}: <strong>{result.best}</strong>
                            </div>
                            {result.summary && <p className="lab-verdict-summary">{result.summary}</p>}
                            <ul className="lab-verdict-list">
                              {result.rankings.map((rk, i) => (
                                <li key={i} className="lab-verdict-item">
                                  <span className="lab-verdict-score">{rk.score}</span>
                                  <span className="lab-verdict-label">{rk.label}</span>
                                  <span className="lab-verdict-comment text-muted">{rk.comment}</span>
                                </li>
                              ))}
                            </ul>
                            {result.fields && Object.keys(result.fields).length > 0 && (
                              <div style={{ marginTop: 8 }}>
                                <p className="text-xs text-muted" style={{ marginBottom: 4 }}>{lab.judgeFields}</p>
                                <FieldChips fields={result.fields} />
                              </div>
                            )}
                            {(result.corrected || result.fields) && (
                              <div style={{ marginTop: 10 }}>
                                {result.corrected && (
                                  <>
                                    <p className="text-xs text-muted" style={{ marginBottom: 4 }}>{lab.corrected}</p>
                                    <pre className="lab-card-text" style={{ height: 120 }}>{result.corrected}</pre>
                                  </>
                                )}
                                <div style={{ marginTop: 6 }}>
                                  {(() => {
                                    const fakeId = `judge-${p.id}`;
                                    const isSaving = savingId === fakeId;
                                    const isSaved = savedId === fakeId;
                                    return (
                                      <button
                                        className={`lab-save-btn-inline${isSaved ? " saved" : ""}`}
                                        title={isSaved ? lab.saved : lab.saveResult}
                                        disabled={isSaving || (!result.corrected && !result.fields)}
                                        onClick={() => handleSaveJudge(p.id, p.name, result)}
                                      >
                                        <Save size={12} />
                                        {isSaved ? lab.saved : isSaving ? lab.saving : lab.saveResult}
                                      </button>
                                    );
                                  })()}
                                </div>
                              </div>
                            )}
                            <p className="text-xs text-muted" style={{ marginTop: 6 }}>
                              {formatMs(result.ms)}
                              {result.tokens_in ? ` · ${result.tokens_in}↑${result.tokens_out}↓ tok` : ""}
                              {result.cost > 0 ? ` · $${result.cost.toFixed(5)}` : ""}
                            </p>
                          </div>
                        )}
                      </div>
                    );
                  })}
              </>
            )}
          </section>
        </aside>
      </div>

      {/* Floating text modal */}
      {expandedResult && (
        <div className="lab-float-modal" style={{ left: modalPos.x, top: modalPos.y }}>
          <div className="lab-float-header" onMouseDown={e => onModalDragStart(e, modalPos)}>
            <span className={`lab-kind ${expandedResult.kind}`}>
              {expandedResult.kind === "ocr" ? "OCR" : "AI"}
            </span>
            <span className="lab-float-label">{expandedResult.label}</span>
            <span className="lab-float-time text-muted">{formatMs(expandedResult.ms)}</span>
            {(() => {
              const isSaving = savingId === expandedResult.id;
              const isSaved = savedId === expandedResult.id;
              return (
                <button
                  className={`icon-btn lab-save-btn${isSaved ? " saved" : ""}`}
                  title={isSaved ? lab.saved : lab.saveResult}
                  disabled={isSaving}
                  onClick={() => handleSave(expandedResult)}
                >
                  <Save size={13} />
                </button>
              );
            })()}
            <button className="icon-btn" onClick={() => setExpandedResult(null)} title={lab.remove}>
              <X size={13} />
            </button>
          </div>
          {expandedResult.fields && Object.keys(expandedResult.fields).length > 0 && (
            <div className="lab-float-fields">
              <FieldChips fields={expandedResult.fields} />
            </div>
          )}
          <pre className="lab-float-text">{expandedResult.text || "—"}</pre>
        </div>
      )}
    </div>
  );
}
