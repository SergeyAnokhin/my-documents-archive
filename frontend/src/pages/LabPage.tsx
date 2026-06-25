import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, ZoomIn, ZoomOut, Maximize, Maximize2, Play, X, Scale, Trophy, Terminal,
} from "lucide-react";
import { Button } from "../components/ui/Button";
import { useT } from "../i18n";
import {
  getDocument, getLabMethods, listProviders,
  runLabOcr, runLabVision, runLabJudge,
} from "../api/documents";
import type {
  Document, AIProvider, LabMethods, LabResult, LabJudgeResult,
} from "../types";
import "./LabPage.css";

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

  // Judge — multi-select
  const [judgeProviders, setJudgeProviders] = useState<number[]>([]);
  const [judgingIds, setJudgingIds] = useState<number[]>([]);
  const [judgeResults, setJudgeResults] = useState<Record<number, LabJudgeResult>>({});
  const [judgeErrors, setJudgeErrors] = useState<Record<number, string>>({});

  // Zoom
  const [zoom, setZoom] = useState(1);

  // Resizable split — width persisted in localStorage
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

  // Floating text modal
  const [expandedResult, setExpandedResult] = useState<LabResult | null>(null);
  const [modalPos, setModalPos] = useState({ x: 24, y: 80 });
  const modalDragStart = useRef<{ mx: number; my: number; px: number; py: number } | null>(null);

  const onModalDragStart = (e: React.MouseEvent, curPos: { x: number; y: number }) => {
    modalDragStart.current = { mx: e.clientX, my: e.clientY, px: curPos.x, py: curPos.y };
    e.preventDefault();
  };

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
    };
    const onUp = () => {
      if (isResizing.current) {
        try { localStorage.setItem("lab-panel-width", String(panelWidthRef.current)); } catch {}
      }
      isResizing.current = false;
      modalDragStart.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  // Logs
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

  // Replace any prior result with the same label, then append the fresh one.
  const upsert = (r: LabResult) =>
    setResults(prev => [...prev.filter(p => p.label !== r.label), r]);

  const handleOcr = async (method: string) => {
    setRunningOcr(method);
    addLog(`→ OCR [${method}]`);
    try {
      const res = await runLabOcr(docId, method);
      upsert({ id: uid(), kind: "ocr", label: method, text: res.text, ms: res.ms });
      addLog(`← OCR [${method}]: ${res.text.length} chars · ${res.ms}ms`, "ok");
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
      upsert({ id: uid(), kind: "vision", label: p.name, providerId: p.id, text: res.text, ms: res.ms, cost: res.cost, tokens_in: res.tokens_in, tokens_out: res.tokens_out });
      const costStr = res.cost != null && res.cost > 0 ? ` · $${res.cost.toFixed(5)}` : "";
      const tokStr = res.tokens_in ? ` · ${res.tokens_in}+${res.tokens_out} tok` : "";
      addLog(`← Vision [${p.name}]: ${res.text.length} chars · ${res.ms}ms${tokStr}${costStr}`, "ok");
    } catch (e) {
      upsert({ id: uid(), kind: "vision", label: p.name, providerId: p.id, text: `⚠️ ${lab.failed}: ${(e as Error).message}`, ms: 0 });
      addLog(`✗ Vision [${p.name}]: ${(e as Error).message}`, "err");
    } finally {
      setRunningVision(null);
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
        addLog(`← Judge [${provider.name}]: best="${res.best}" · ${res.ms}ms${costStr}`, "ok");
      } catch (e) {
        setJudgeErrors(prev => ({ ...prev, [providerId]: (e as Error).message }));
        addLog(`✗ Judge [${provider.name}]: ${(e as Error).message}`, "err");
      } finally {
        setJudgingIds(prev => prev.filter(id => id !== providerId));
      }
    }));
  };

  const downloadUrl = `/api/documents/${docId}/download?inline=1`;
  const isPdf = doc?.mime_type === "application/pdf" || doc?.filename.toLowerCase().endsWith(".pdf");

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
            <button className="icon-btn" title={lab.zoomOut} onClick={() => setZoom(z => Math.max(0.25, z - 0.25))} disabled={isPdf}>
              <ZoomOut size={16} />
            </button>
            <span className="text-xs text-muted" style={{ minWidth: 42, textAlign: "center" }}>
              {Math.round(zoom * 100)}%
            </span>
            <button className="icon-btn" title={lab.zoomIn} onClick={() => setZoom(z => Math.min(5, z + 0.25))} disabled={isPdf}>
              <ZoomIn size={16} />
            </button>
            <button className="icon-btn" title={lab.resetZoom} onClick={() => setZoom(1)} disabled={isPdf}>
              <Maximize size={16} />
            </button>
          </div>
          <div className="lab-doc-canvas">
            {isPdf ? (
              <iframe src={downloadUrl} title={doc?.filename} className="lab-doc-pdf" />
            ) : (
              <img
                src={downloadUrl}
                alt={doc?.filename}
                className="lab-doc-img"
                style={{ width: `${zoom * 100}%` }}
              />
            )}
          </div>
        </div>

        {/* Drag handle */}
        <div className="lab-resizer" onMouseDown={onResizerDown} />

        {/* Right — experiments */}
        <aside className="lab-panel">
          {/* Subtitle + logs toggle */}
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
                <span
                  className="status-dot done pulse"
                  title="Compute-сервис доступен"
                  style={{ marginTop: 1 }}
                />
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
                      variant="secondary"
                      size="sm"
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
                  return (
                    <div key={r.id} className={`lab-card${isBest ? " best" : ""}`}>
                      <div className="lab-card-head">
                        <span className={`lab-kind ${r.kind}`}>{r.kind === "ocr" ? "OCR" : "AI"}</span>
                        <span className="lab-card-label">{r.label}</span>
                        {isBest && <Trophy size={13} className="lab-best-icon" />}
                        <span className="lab-card-meta">
                          {r.text.length} {lab.chars} · {r.ms} ms
                          {(r.tokens_in != null && r.tokens_in > 0) ? ` · ${r.tokens_in}↑${r.tokens_out}↓ tok` : ""}
                          {r.cost != null && r.cost > 0 ? ` · $${r.cost.toFixed(5)}` : ""}
                        </span>
                        <button className="icon-btn" title={lab.expand}
                          onClick={() => { setExpandedResult(r); setModalPos({ x: 24, y: 80 }); }}>
                          <Maximize2 size={13} />
                        </button>
                        <button className="icon-btn" title={lab.remove}
                          onClick={() => setResults(prev => prev.filter(x => x.id !== r.id))}>
                          <X size={13} />
                        </button>
                      </div>
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

                {/* Multi-select judge list */}
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
                  variant="primary"
                  size="sm"
                  icon={<Scale size={14} />}
                  loading={judgingIds.length > 0}
                  disabled={results.length < 2 || judgeProviders.length === 0}
                  onClick={handleJudge}
                  style={{ marginTop: 8 }}
                >
                  {judgingIds.length > 0 ? lab.comparing : lab.compare}
                </Button>
                {results.length < 2 && <p className="text-xs text-muted" style={{ marginTop: 6 }}>{lab.needTwo}</p>}

                {/* One verdict block per judge that has a result or error */}
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
                            {result.corrected && (
                              <div style={{ marginTop: 10 }}>
                                <p className="text-xs text-muted" style={{ marginBottom: 4 }}>{lab.corrected}</p>
                                <pre className="lab-card-text" style={{ height: 120 }}>{result.corrected}</pre>
                              </div>
                            )}
                            <p className="text-xs text-muted" style={{ marginTop: 6 }}>
                              {result.ms} ms
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
        <div
          className="lab-float-modal"
          style={{ left: modalPos.x, top: modalPos.y }}
        >
          <div
            className="lab-float-header"
            onMouseDown={e => onModalDragStart(e, modalPos)}
          >
            <span className={`lab-kind ${expandedResult.kind}`}>
              {expandedResult.kind === "ocr" ? "OCR" : "AI"}
            </span>
            <span className="lab-float-label">{expandedResult.label}</span>
            <button className="icon-btn" onClick={() => setExpandedResult(null)} title={lab.remove}>
              <X size={13} />
            </button>
          </div>
          <pre className="lab-float-text">{expandedResult.text || "—"}</pre>
        </div>
      )}
    </div>
  );
}
