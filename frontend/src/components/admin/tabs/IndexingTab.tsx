import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import { getStats, syncLibrary, reclassifyAll } from "../../../api/documents";
import { api } from "../../../api/client";
import type { IndexingStats } from "../../../types";

export function IndexingTab() {
  const { t } = useT();
  const [stats, setStats] = useState<IndexingStats | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [batching, setBatching] = useState(false);
  const [reclassifying, setReclassifying] = useState(false);
  const [msg, setMsg] = useState("");

  const loadStats = () => getStats().then(setStats).catch(() => {});
  useEffect(() => { loadStats(); }, []);

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

  return (
    <div className="admin-section">
      <h3 className="admin-section-title">{t.admin.indexing.title}</h3>

      {stats && (
        <>
          <div className="stats-grid">
            <StatCard label={t.admin.indexing.total}    value={stats.total} />
            <StatCard label={t.admin.indexing.indexed}  value={stats.indexed} accent />
            <StatCard label={t.admin.indexing.analyzed} value={stats.analyzed} accent />
            <StatCard label={t.admin.indexing.embedded} value={stats.embedded} accent />
            <StatCard label={t.admin.indexing.pending}  value={stats.pending} />
            <StatCard label={t.admin.indexing.errors}   value={stats.errors} danger={stats.errors > 0} />
          </div>
          {stats.api_cost_total > 0 && (
            <p className="text-xs text-muted" style={{ marginTop: 8 }}>
              {t.admin.indexing.cost}: ${stats.api_cost_total.toFixed(4)}
            </p>
          )}
        </>
      )}

      {msg && <p className="admin-msg">{msg}</p>}

      <div className="admin-actions">
        <Button variant="primary" icon={<RefreshCw size={15} />} loading={syncing} onClick={handleSync}>
          {t.admin.indexing.syncButton}
        </Button>
        <Button variant="secondary" loading={batching} onClick={handleBatch}>
          {t.admin.indexing.batchButton}
        </Button>
        <Button variant="secondary" loading={reclassifying} onClick={handleReclassify}>
          {t.admin.indexing.reclassifyButton}
        </Button>
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
