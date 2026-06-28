import { useState, useEffect } from "react";
import { RefreshCw, ChevronUp, ChevronDown } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import { getStats, syncLibrary, reclassifyAll, reclassifyUnclassified, recluster, getAppSettings, updateAppSettings, getWorkerStatus, updateTypeIcons } from "../../../api/documents";
import { setCustomTypeIcons } from "../../documents/typeIcons";
import { api } from "../../../api/client";
import type { IndexingStats, LabWorkerStatus } from "../../../types";

export function IndexingTab() {
  const { t } = useT();
  const [stats, setStats] = useState<IndexingStats | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [batching, setBatching] = useState(false);
  const [reclassifying, setReclassifying] = useState(false);
  const [reclassifyingUnclassified, setReclassifyingUnclassified] = useState(false);
  const [reclustering, setReclustering] = useState(false);
  const [updatingIcons, setUpdatingIcons] = useState(false);
  const [msg, setMsg] = useState("");
  const [syncResult, setSyncResult] = useState<{ added: number; removed: number } | null>(null);

  // Compute worker settings
  const [workerUrl, setWorkerUrl] = useState("");
  const [checkingEngine, setCheckingEngine] = useState<"tesseract" | "easyocr" | null>(null);
  const [workerStatus, setWorkerStatus_] = useState<LabWorkerStatus | null>(null);
  const [savingUrl, setSavingUrl] = useState(false);

  // OCR engine priority
  const [ocrEngines, setOcrEngines] = useState<string[]>(["easyocr", "tesseract"]);
  const [savingPriority, setSavingPriority] = useState(false);

  // Auto-process mode
  const [autoProcessMode, setAutoProcessMode] = useState("full");
  const [savingMode, setSavingMode] = useState(false);

  const loadStats = () => getStats().then(setStats).catch(() => {});
  useEffect(() => { loadStats(); }, []);

  useEffect(() => {
    getAppSettings().then(s => {
      setWorkerUrl(s.ocr_worker_url ?? "");
      if (s.ocr_priority) {
        setOcrEngines(s.ocr_priority.split(",").map((e: string) => e.trim()).filter(Boolean));
      }
      if (s.auto_process_mode) setAutoProcessMode(s.auto_process_mode);
    }).catch(() => {});
  }, []);

  // Auto-probe the worker 700 ms after the user stops typing / pastes a URL.
  useEffect(() => {
    if (!workerUrl.trim()) { setWorkerStatus_(null); return; }
    const id = setTimeout(() => { handleCheckEngine("tesseract"); }, 700);
    return () => clearTimeout(id);
  }, [workerUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  const flash = (text: string) => { setMsg(text); setTimeout(() => setMsg(""), 4000); };

  const handleUpdateIcons = async () => {
    setUpdatingIcons(true);
    try {
      const res = await updateTypeIcons();
      setCustomTypeIcons(res.icons);
      window.dispatchEvent(new CustomEvent("docintell:library-changed"));
      flash(res.updated > 0
        ? ix.updateIconsDone.replace("{{n}}", String(res.updated))
        : ix.updateIconsNone);
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setUpdatingIcons(false);
    }
  };

  const handleSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const res = await syncLibrary();
      setSyncResult({ added: res.new_files, removed: res.removed ?? 0 });
      await loadStats();
      window.dispatchEvent(new CustomEvent("docintell:library-changed"));
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setSyncing(false);
    }
  };

  const handleBatch = async () => {
    setBatching(true);
    try {
      await api.post("/admin/batch-index");
      flash("Batch indexing started in background…");
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setBatching(false);
    }
  };

  const handleReclassify = async () => {
    setReclassifying(true);
    try {
      await reclassifyAll();
      flash("Re-classification started in background…");
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setReclassifying(false);
    }
  };

  const handleReclassifyUnclassified = async () => {
    setReclassifyingUnclassified(true);
    try {
      await reclassifyUnclassified();
      flash("Classifying unclassified documents…");
      await loadStats();
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setReclassifyingUnclassified(false);
    }
  };

  const handleRecluster = async () => {
    setReclustering(true);
    try {
      await recluster();
      flash("Cluster-based recategorization started in background…");
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setReclustering(false);
    }
  };

  const moveEngine = async (index: number, dir: "up" | "down") => {
    const swapIdx = dir === "up" ? index - 1 : index + 1;
    if (swapIdx < 0 || swapIdx >= ocrEngines.length) return;
    const next = [...ocrEngines];
    [next[index], next[swapIdx]] = [next[swapIdx], next[index]];
    setOcrEngines(next);
    setSavingPriority(true);
    try {
      await updateAppSettings({ ocr_priority: next.join(",") });
    } finally {
      setSavingPriority(false);
    }
  };

  const handleSaveMode = async (value: string) => {
    setAutoProcessMode(value);
    setSavingMode(true);
    try {
      await updateAppSettings({ auto_process_mode: value });
      flash(ix.autoProcessSaved);
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setSavingMode(false);
    }
  };

  const handleSaveUrl = async () => {
    setSavingUrl(true);
    try {
      await updateAppSettings({ ocr_worker_url: workerUrl.trim() });
      flash(t.admin.indexing.workerSaved);
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setSavingUrl(false);
    }
  };

  const handleCheckEngine = async (engine: "tesseract" | "easyocr") => {
    setCheckingEngine(engine);
    setWorkerStatus_(null);
    try {
      if (workerUrl.trim()) {
        await updateAppSettings({ ocr_worker_url: workerUrl.trim() });
      }
      const status = await getWorkerStatus();
      setWorkerStatus_(status);
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setCheckingEngine(null);
    }
  };

  const ix = t.admin.indexing;

  return (
    <div className="admin-section">
      <h3 className="admin-section-title">{ix.title}</h3>

      {stats?.library_path && (
        <div style={{ marginBottom: 12, fontSize: "0.8125rem", color: "var(--color-muted)" }}>
          <span style={{ fontWeight: 500, color: "var(--color-text)" }}>{ix.libraryFolder}: </span>
          <span className="text-mono">{stats.library_path}</span>
        </div>
      )}

      {stats && (
        <>
          <div className="stats-grid">
            <StatCard label={ix.total}        value={stats.total} />
            <StatCard label={ix.indexed}      value={stats.indexed} accent />
            <StatCard label={ix.analyzed}     value={stats.analyzed} accent />
            <StatCard label={ix.embedded}     value={stats.embedded} accent />
            <StatCard label={ix.pending}      value={stats.pending} />
            <StatCard label={ix.errors}       value={stats.errors} danger={stats.errors > 0} />
            <StatCard label={ix.unclassified} value={stats.unclassified} danger={stats.unclassified > 0} />
          </div>
          {stats.api_cost_total > 0 && (
            <p className="text-xs text-muted" style={{ marginTop: 8 }}>
              {ix.cost}: ${stats.api_cost_total.toFixed(4)}
            </p>
          )}
        </>
      )}

      {msg && <p className="admin-msg">{msg}</p>}

      {syncResult && (
        <div className="sync-result">
          <span className="sync-result-item sync-result-added">
            +{syncResult.added} {t.syncAdded}
          </span>
          {syncResult.removed > 0 && (
            <span className="sync-result-item sync-result-removed">
              −{syncResult.removed} {t.syncRemoved}
            </span>
          )}
          {syncResult.added === 0 && syncResult.removed === 0 && (
            <span className="sync-result-item">{t.syncNoChanges}</span>
          )}
        </div>
      )}

      <div className="admin-actions">
        <Button variant="primary" icon={<RefreshCw size={15} />} loading={syncing} onClick={handleSync}>
          {ix.syncButton}
        </Button>
        <Button variant="secondary" loading={batching} onClick={handleBatch}>
          {ix.batchButton}
        </Button>
        <Button variant="secondary" loading={reclassifying} onClick={handleReclassify}>
          {ix.reclassifyButton}
        </Button>
        <Button variant="secondary" loading={reclassifyingUnclassified} onClick={handleReclassifyUnclassified}>
          {ix.reclassifyUnclassifiedButton}
        </Button>
        <Button variant="secondary" loading={reclustering} onClick={handleRecluster}>
          {ix.reclusterButton}
        </Button>
        <Button variant="secondary" loading={updatingIcons} onClick={handleUpdateIcons}>
          {ix.updateIconsButton}
        </Button>
      </div>

      {/* Auto-process mode */}
      <h3 className="admin-section-title" style={{ marginTop: 24 }}>{ix.autoProcessMode}</h3>
      <p className="text-xs text-muted" style={{ marginBottom: 10 }}>{ix.autoProcessHint}</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {(["full", "ocr_only", "manual"] as const).map(mode => (
          <label key={mode} style={{ display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer", opacity: savingMode ? 0.6 : 1 }}>
            <input
              type="radio"
              name="auto_process_mode"
              value={mode}
              checked={autoProcessMode === mode}
              onChange={() => handleSaveMode(mode)}
              style={{ marginTop: 2, flexShrink: 0 }}
            />
            <span style={{ fontSize: "0.875rem" }}>
              {mode === "full" ? ix.autoProcessFull : mode === "ocr_only" ? ix.autoProcessOcrOnly : ix.autoProcessManual}
            </span>
          </label>
        ))}
      </div>

      {/* Compute Worker */}
      <div style={{ marginTop: 24 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
          <h3 className="admin-section-title">{ix.computeWorker}</h3>
          {checkingEngine ? (
            <span style={{ fontSize: 12, color: "var(--color-ink-muted)" }}>…</span>
          ) : workerStatus?.reachable ? (
            <>
              <span className="status-dot done pulse" />
              <span className="engine-pill ok"><span className="engine-pill-dot" />Tesseract</span>
              <span className={`engine-pill ${workerStatus.engines.includes("easyocr") ? "ok" : "err"}`}>
                <span className="engine-pill-dot" />EasyOCR
              </span>
            </>
          ) : workerStatus && !workerStatus.reachable ? (
            <span style={{ fontSize: 12, color: "var(--color-error)", fontWeight: 500 }}>● {ix.workerDown}</span>
          ) : null}
          <button
            className="icon-btn"
            title="Check"
            disabled={!workerUrl.trim() || checkingEngine !== null}
            onClick={() => handleCheckEngine("tesseract")}
            style={{ marginLeft: "auto", opacity: !workerUrl.trim() ? 0.3 : 1 }}
          >
            <RefreshCw size={13} />
          </button>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="admin-input"
            value={workerUrl}
            onChange={e => { setWorkerUrl(e.target.value); setWorkerStatus_(null); }}
            placeholder={ix.workerUrlPlaceholder}
            style={{ flex: 1 }}
          />
          <Button variant="secondary" loading={savingUrl} onClick={handleSaveUrl}>
            {t.save ?? "Save"}
          </Button>
        </div>
      </div>

      {/* OCR Engine Priority */}
      <div style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 6 }}>
          <span style={{ fontSize: 13, fontWeight: 600 }}>{ix.ocrPriority}</span>
          <p className="text-xs text-muted" style={{ marginTop: 2 }}>{ix.ocrPriorityHint}</p>
        </div>
        <ul className="provider-list">
          {ocrEngines.map((engine, i) => (
            <li key={engine} className="provider-item" style={{ padding: "5px 8px" }}>
              <div style={{ display: "flex", flexDirection: "row", gap: 1, flexShrink: 0 }}>
                <button className="icon-btn" onClick={() => moveEngine(i, "up")}
                  disabled={i === 0 || savingPriority} style={{ opacity: i === 0 ? 0.25 : 1 }}
                  title={t.admin.ai.moveUp}>
                  <ChevronUp size={13} />
                </button>
                <button className="icon-btn" onClick={() => moveEngine(i, "down")}
                  disabled={i === ocrEngines.length - 1 || savingPriority}
                  style={{ opacity: i === ocrEngines.length - 1 ? 0.25 : 1 }}
                  title={t.admin.ai.moveDown}>
                  <ChevronDown size={13} />
                </button>
              </div>
              <span className="provider-name">{engine === "easyocr" ? "EasyOCR" : "Tesseract"}</span>
            </li>
          ))}
        </ul>
      </div>

    </div>
  );
}

function StatCard({ label, value, accent, danger }: { label: string; value: number; accent?: boolean; danger?: boolean }) {
  return (
    <div className={`stat-card${accent ? " accent" : danger ? " danger" : ""}`}>
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
