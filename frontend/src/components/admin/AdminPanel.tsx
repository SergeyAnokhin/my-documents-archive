import { useState, useEffect } from "react";
import { BarChart2, Folder, Settings, ScrollText, RefreshCw, Plus, Trash2 } from "lucide-react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";
import {
  getStats, syncLibrary,
  listFolders, addFolder, removeFolder, toggleFolder,
  listProviders, addProvider, toggleProvider, removeProvider,
  reclassifyAll,
  getAppSettings, updateAppSettings,
  getLog,
} from "../../api/documents";
import { api } from "../../api/client";
import type { IndexingStats, WatchedFolder, AIProvider, LogEntry } from "../../types";
import "./AdminPanel.css";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Tab = "sources" | "indexing" | "ai" | "log";

export function AdminPanel({ open, onClose }: Props) {
  const { t } = useT();
  const [tab, setTab] = useState<Tab>("indexing");

  return (
    <Modal open={open} onClose={onClose} size="lg" title={t.admin.title}>
      <div className="admin-layout">
        {/* Sidebar tabs */}
        <nav className="admin-nav">
          {(["indexing", "sources", "ai", "log"] as Tab[]).map((id) => {
            const icons: Record<Tab, JSX.Element> = {
              indexing: <BarChart2 size={16} />,
              sources:  <Folder size={16} />,
              ai:       <Settings size={16} />,
              log:      <ScrollText size={16} />,
            };
            const labels: Record<Tab, string> = {
              indexing: t.admin.tabs.indexing,
              sources:  t.admin.tabs.sources,
              ai:       t.admin.tabs.ai,
              log:      t.admin.tabs.log,
            };
            return (
              <button
                key={id}
                className={`admin-nav-btn${tab === id ? " active" : ""}`}
                onClick={() => setTab(id)}
              >
                {icons[id]}
                <span>{labels[id]}</span>
              </button>
            );
          })}
        </nav>

        {/* Tab content */}
        <div className="admin-content">
          {tab === "indexing" && <IndexingTab />}
          {tab === "sources"  && <SourcesTab />}
          {tab === "ai"       && <AITab />}
          {tab === "log"      && <LogTab />}
        </div>
      </div>
    </Modal>
  );
}

/* ── Indexing Tab ────────────────────────────────────────────────────────── */
function IndexingTab() {
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

/* ── Sources Tab ──────────────────────────────────────────────────────────── */
function SourcesTab() {
  const { t } = useT();
  const [folders, setFolders] = useState<WatchedFolder[]>([]);
  const [newPath, setNewPath] = useState("");
  const [adding, setAdding] = useState(false);

  const load = () => listFolders().then(setFolders).catch(() => {});

  useEffect(() => { load(); }, []);

  const handleAdd = async () => {
    if (!newPath.trim()) return;
    setAdding(true);
    try {
      await addFolder(newPath.trim());
      setNewPath("");
      await load();
    } catch {
      /* ignore for now */
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="admin-section">
      <h3 className="admin-section-title">{t.admin.sources.title}</h3>

      {folders.length === 0 ? (
        <p className="text-muted">{t.admin.sources.noFolders}</p>
      ) : (
        <ul className="folder-list">
          {folders.map((f) => (
            <li key={f.id} className="folder-item">
              <span className={`folder-path text-mono text-sm${!f.enabled ? " disabled" : ""}`}>{f.path}</span>
              <div className="folder-actions">
                <button
                  className="icon-btn"
                  onClick={() => toggleFolder(f.id).then(load)}
                  title={f.enabled ? t.enabled : t.disabled}
                >
                  <span className={`status-dot ${f.enabled ? "done" : "pending"}`} />
                </button>
                <button
                  className="icon-btn"
                  onClick={() => removeFolder(f.id).then(load)}
                  title={t.delete}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="folder-add">
        <input
          className="admin-input"
          placeholder={t.admin.sources.folderPath}
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
        />
        <Button variant="primary" size="sm" icon={<Plus size={14} />} loading={adding} onClick={handleAdd}>
          {t.add}
        </Button>
      </div>
    </div>
  );
}

/* ── AI Tab ───────────────────────────────────────────────────────────────── */
const EMPTY_FORM = { name: "", provider_type: "anthropic", api_key: "", base_url: "", model: "" };

function AITab() {
  const { t } = useT();
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [visionEnabled, setVisionEnabled] = useState(false);
  const [togglingVision, setTogglingVision] = useState(false);

  const load = () => listProviders().then(setProviders).catch(() => {});
  useEffect(() => {
    load();
    getAppSettings()
      .then((s) => setVisionEnabled(s["enable_ai_vision"] === "true"))
      .catch(() => {});
  }, []);

  const handleVisionToggle = async () => {
    setTogglingVision(true);
    const next = !visionEnabled;
    try {
      await updateAppSettings({ enable_ai_vision: next ? "true" : "false" });
      setVisionEnabled(next);
    } catch {
      /* ignore */
    } finally {
      setTogglingVision(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await addProvider({
        ...form,
        base_url: form.base_url || undefined,
        model: form.model || undefined,
      });
      setShowForm(false);
      setForm(EMPTY_FORM);
      await load();
    } finally {
      setSaving(false);
    }
  };

  const active = providers.find((p) => p.enabled);

  return (
    <div className="admin-section">
      <h3 className="admin-section-title">{t.admin.ai.title}</h3>

      {active && (
        <p className="text-xs text-muted" style={{ marginBottom: 12 }}>
          ✓ Analysis provider: <strong>{active.name}</strong>
          {active.model ? ` (${active.model})` : ""}
        </p>
      )}

      {/* Vision toggle */}
      <div className="provider-item" style={{ marginBottom: 16 }}>
        <div>
          <span className="provider-name">{t.admin.ai.enableVision}</span>
          <p className="text-xs text-muted" style={{ marginTop: 2 }}>{t.admin.ai.visionHint}</p>
        </div>
        <button
          className="icon-btn"
          onClick={handleVisionToggle}
          disabled={togglingVision}
          title={visionEnabled ? t.enabled : t.disabled}
        >
          <span className={`status-dot ${visionEnabled ? "done" : "pending"}`} />
        </button>
      </div>

      {providers.length === 0 ? (
        <>
          <p className="text-muted">{t.admin.ai.noProviders}</p>
          <p className="text-xs text-muted" style={{ marginTop: 4 }}>{t.admin.ai.noProvidersHint}</p>
        </>
      ) : (
        <ul className="provider-list">
          {providers.map((p) => (
            <li key={p.id} className="provider-item">
              <div>
                <span className="provider-name">{p.name}</span>
                <span className="text-xs text-muted"> · {p.provider_type}</span>
                {p.model && <span className="text-xs text-muted"> · {p.model}</span>}
              </div>
              <div className="folder-actions">
                <button
                  className="icon-btn"
                  onClick={() => toggleProvider(p.id).then(load)}
                  title={p.enabled ? t.enabled : t.disabled}
                >
                  <span className={`status-dot ${p.enabled ? "done" : "pending"}`} />
                </button>
                <button className="icon-btn" onClick={() => removeProvider(p.id).then(load)} title={t.delete}>
                  <Trash2 size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!showForm ? (
        <Button variant="secondary" size="sm" icon={<Plus size={14} />} onClick={() => setShowForm(true)}>
          {t.admin.ai.addProvider}
        </Button>
      ) : (
        <div className="provider-form">
          <input className="admin-input" placeholder={t.admin.ai.providerName} value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="admin-input" value={form.provider_type}
            onChange={(e) => setForm({ ...form, provider_type: e.target.value })}>
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="openai">OpenAI / OpenAI-compatible</option>
            <option value="gemini">Google Gemini</option>
            <option value="deepseek">DeepSeek</option>
            <option value="openrouter">OpenRouter</option>
          </select>
          <input className="admin-input" placeholder={t.admin.ai.apiKey} type="password" value={form.api_key}
            onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
          <input className="admin-input" placeholder="Base URL (optional)" value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
          <input className="admin-input" placeholder={t.admin.ai.modelName} value={form.model}
            onChange={(e) => setForm({ ...form, model: e.target.value })} />
          <div style={{ display: "flex", gap: 8 }}>
            <Button variant="primary" size="sm" loading={saving} onClick={handleSave}>{t.save}</Button>
            <Button variant="ghost" size="sm" onClick={() => setShowForm(false)}>{t.cancel}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Log Tab ──────────────────────────────────────────────────────────────── */
function LogTab() {
  const { t } = useT();
  const [log, setLog] = useState<LogEntry[]>([]);

  useEffect(() => {
    getLog(50).then(setLog).catch(() => {});
  }, []);

  if (log.length === 0) return <p className="text-muted">{t.admin.log.empty}</p>;

  return (
    <div className="log-list">
      {log.map((entry) => (
        <div key={entry.id} className="log-row">
          <span className={`status-dot ${entry.status === "done" ? "done" : entry.status === "error" ? "error" : "pending"}`} />
          <span className="text-xs text-muted log-time">
            {entry.created_at ? new Date(entry.created_at).toLocaleTimeString() : ""}
          </span>
          <span className="log-step text-xs">{entry.step}</span>
          <span className="text-sm truncate">{entry.message}</span>
        </div>
      ))}
    </div>
  );
}
