import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft, ZoomIn, ZoomOut, Maximize, Play, X, Scale, Trophy, Terminal,
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

const VISION_CAPABLE = ["anthropic", "openai", "gemini", "openrouter"];

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
  const { t } = useT();
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
  const [judgeProvider, setJudgeProvider] = useState<number | null>(null);
  const [useImage, setUseImage] = useState(true);
  const [judging, setJudging] = useState(false);
  const [judgeResult, setJudgeResult] = useState<LabJudgeResult | null>(null);
  const [judgeError, setJudgeError] = useState("");

  // Zoom
  const [zoom, setZoom] = useState(1);

  // Resizable split
  const [panelWidth, setPanelWidth] = useState(440);
  const isResizing = useRef(false);
  const resizeStartX = useRef(0);
  const resizeStartWidth = useRef(440);

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
      setPanelWidth(Math.max(300, Math.min(900, resizeStartWidth.current + dx)));
    };
    const onUp = () => { isResizing.current = false; };
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

  useEffect(() => {
    if (judgeProvider === null && premiumProviders.length > 0) {
      setJudgeProvider(premiumProviders[0].id);
    }
  }, [premiumProviders, judgeProvider]);

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
    if (judgeProvider === null || results.length < 2) return;
    setJudging(true);
    setJudgeError("");
    setJudgeResult(null);
    const judgeName = premiumProviders.find(p => p.id === judgeProvider)?.name ?? String(judgeProvider);
    addLog(`→ Judge [${judgeName}] on ${results.length} candidates`);
    try {
      const res = await runLabJudge({
        doc_id: docId,
        provider_id: judgeProvider,
        use_image: useImage,
        candidates: results.map(r => ({ label: r.label, text: r.text })),
      });
      setJudgeResult(res);
      const costStr = res.cost > 0 ? ` · $${res.cost.toFixed(5)}` : "";
      addLog(`← Judge: best="${res.best}" · ${res.ms}ms${costStr}`, "ok");
    } catch (e) {
      setJudgeError((e as Error).message);
      addLog(`✗ Judge [${judgeName}]: ${(e as Error).message}`, "err");
    } finally {
      setJudging(false);
    }
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
            <h3 className="lab-section-title">{lab.localOcr}</h3>
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
                  const isBest = judgeResult?.best === r.label;
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
                <select
                  className="admin-input"
                  value={judgeProvider ?? ""}
                  onChange={e => setJudgeProvider(Number(e.target.value))}
                >
                  {premiumProviders.map(p => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <label className="lab-checkbox">
                  <input type="checkbox" checked={useImage} onChange={e => setUseImage(e.target.checked)} />
                  {lab.useImage}
                </label>
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Scale size={14} />}
                  loading={judging}
                  disabled={results.length < 2}
                  onClick={handleJudge}
                  style={{ marginTop: 8 }}
                >
                  {judging ? lab.comparing : lab.compare}
                </Button>
                {results.length < 2 && <p className="text-xs text-muted" style={{ marginTop: 6 }}>{lab.needTwo}</p>}
                {judgeError && <p className="text-xs" style={{ color: "var(--color-error)", marginTop: 6 }}>{judgeError}</p>}

                {judgeResult && (
                  <div className="lab-verdict">
                    <div className="lab-verdict-best">
                      <Trophy size={15} /> {lab.best}: <strong>{judgeResult.best}</strong>
                    </div>
                    {judgeResult.summary && <p className="lab-verdict-summary">{judgeResult.summary}</p>}
                    <ul className="lab-verdict-list">
                      {judgeResult.rankings.map((rk, i) => (
                        <li key={i} className="lab-verdict-item">
                          <span className="lab-verdict-score">{rk.score}</span>
                          <span className="lab-verdict-label">{rk.label}</span>
                          <span className="lab-verdict-comment text-muted">{rk.comment}</span>
                        </li>
                      ))}
                    </ul>
                    <p className="text-xs text-muted" style={{ marginTop: 6 }}>
                      {judgeResult.ms} ms
                      {judgeResult.tokens_in ? ` · ${judgeResult.tokens_in}↑${judgeResult.tokens_out}↓ tok` : ""}
                      {judgeResult.cost > 0 ? ` · $${judgeResult.cost.toFixed(5)}` : ""}
                    </p>
                  </div>
                )}
              </>
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
