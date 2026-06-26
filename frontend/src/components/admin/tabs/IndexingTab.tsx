import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import { getStats, syncLibrary, reclassifyAll, reclassifyUnclassified, getAppSettings, updateAppSettings, getWorkerStatus } from "../../../api/documents";
import { api } from "../../../api/client";
import type { IndexingStats, LabWorkerStatus } from "../../../types";

export function IndexingTab() {
  const { t } = useT();
  const [stats, setStats] = useState<IndexingStats | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [batching, setBatching] = useState(false);
  const [reclassifying, setReclassifying] = useState(false);
  const [reclassifyingUnclassified, setReclassifyingUnclassified] = useState(false);
  const [msg, setMsg] = useState("");
  const [syncResult, setSyncResult] = useState<{ added: number; removed: number } | null>(null);

  // Compute worker settings
  const [workerUrl, setWorkerUrl] = useState("");
  const [checkingEngine, setCheckingEngine] = useState<"tesseract" | "easyocr" | null>(null);
  const [workerStatus, setWorkerStatus_] = useState<LabWorkerStatus | null>(null);
  const [savingUrl, setSavingUrl] = useState(false);

  const loadStats = () => getStats().then(setStats).catch(() => {});
  useEffect(() => { loadStats(); }, []);

  useEffect(() => {
    getAppSettings().then(s => {
      setWorkerUrl(s.ocr_worker_url ?? "");
    }).catch(() => {});
  }, []);

  const flash = (text: string) => { setMsg(text); setTimeout(() => setMsg(""), 4000); };

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
      </div>

      {/* Compute Worker */}
      <h3 className="admin-section-title" style={{ marginTop: 24 }}>{ix.computeWorker}</h3>
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

      {/* Per-engine test buttons */}
      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <Button
          variant="secondary"
          size="sm"
          loading={checkingEngine === "tesseract"}
          disabled={checkingEngine !== null}
          onClick={() => handleCheckEngine("tesseract")}
        >
          Tesseract
        </Button>
        <Button
          variant="secondary"
          size="sm"
          loading={checkingEngine === "easyocr"}
          disabled={checkingEngine !== null}
          onClick={() => handleCheckEngine("easyocr")}
        >
          EasyOCR
        </Button>
      </div>

      {workerStatus && (
        <div style={{ marginTop: 8, fontSize: "0.875rem", display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          {workerStatus.reachable && (
            <span className="status-dot done pulse" title={ix.workerUp} />
          )}
          <span style={{ color: workerStatus.reachable ? "var(--color-success)" : "var(--color-error)", fontWeight: 500 }}>
            {workerStatus.reachable ? ix.workerUp : ix.workerDown}
          </span>
          {workerStatus.reachable && (
            <>
              <span className="engine-pill ok">
                <span className="engine-pill-dot" />
                Tesseract
              </span>
              <span className={`engine-pill ${workerStatus.engines.includes("easyocr") ? "ok" : "err"}`}>
                <span className="engine-pill-dot" />
                EasyOCR
                {!workerStatus.engines.includes("easyocr") && (
                  <span style={{ fontSize: 10, marginLeft: 2 }}>— {ix.workerNoEasyocr}</span>
                )}
              </span>
            </>
          )}
        </div>
      )}
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
