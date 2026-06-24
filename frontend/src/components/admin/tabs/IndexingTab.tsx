import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import { getStats, syncLibrary, reclassifyAll, getAppSettings, updateAppSettings, getWorkerStatus } from "../../../api/documents";
import { api } from "../../../api/client";
import type { IndexingStats, LabWorkerStatus } from "../../../types";

export function IndexingTab() {
  const { t } = useT();
  const [stats, setStats] = useState<IndexingStats | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [batching, setBatching] = useState(false);
  const [reclassifying, setReclassifying] = useState(false);
  const [msg, setMsg] = useState("");

  // Compute worker settings
  const [workerUrl, setWorkerUrl] = useState("");
  const [checking, setChecking] = useState(false);
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
    try {
      const res = await syncLibrary();
      flash(t.syncSuccess.replace("{{new}}", String(res.new_files)));
      await loadStats();
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

  const handleCheckWorker = async () => {
    setChecking(true);
    setWorkerStatus_(null);
    try {
      // Save URL first so the backend uses the current value
      if (workerUrl.trim()) {
        await updateAppSettings({ ocr_worker_url: workerUrl.trim() });
      }
      const status = await getWorkerStatus();
      setWorkerStatus_(status);
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setChecking(false);
    }
  };

  const ix = t.admin.indexing;

  return (
    <div className="admin-section">
      <h3 className="admin-section-title">{ix.title}</h3>

      {stats && (
        <>
          <div className="stats-grid">
            <StatCard label={ix.total}    value={stats.total} />
            <StatCard label={ix.indexed}  value={stats.indexed} accent />
            <StatCard label={ix.analyzed} value={stats.analyzed} accent />
            <StatCard label={ix.embedded} value={stats.embedded} accent />
            <StatCard label={ix.pending}  value={stats.pending} />
            <StatCard label={ix.errors}   value={stats.errors} danger={stats.errors > 0} />
          </div>
          {stats.api_cost_total > 0 && (
            <p className="text-xs text-muted" style={{ marginTop: 8 }}>
              {ix.cost}: ${stats.api_cost_total.toFixed(4)}
            </p>
          )}
        </>
      )}

      {msg && <p className="admin-msg">{msg}</p>}

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
        <Button variant="secondary" loading={checking} onClick={handleCheckWorker}>
          {ix.checkWorker}
        </Button>
      </div>

      {workerStatus && (
        <div style={{ marginTop: 8, fontSize: "0.875rem", display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
          <span style={{ color: workerStatus.reachable ? "var(--color-success)" : "var(--color-error)", fontWeight: 500 }}>
            {workerStatus.reachable ? ix.workerUp : ix.workerDown}
          </span>
          {workerStatus.reachable && (
            <>
              <span className="text-muted">— {ix.workerEngines}: {workerStatus.engines.join(", ") || "—"}</span>
              {!workerStatus.worker_available && (
                <span style={{ color: "var(--color-error)" }}>({ix.workerNoEasyocr})</span>
              )}
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
