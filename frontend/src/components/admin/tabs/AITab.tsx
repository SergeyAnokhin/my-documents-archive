import { useState, useEffect, useRef } from "react";
import { RefreshCw, Download, Upload } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import {
  listProviders,
  getArenaRatings, refreshArenaRatings,
  getAppSettings, updateAppSettings,
  exportProviders, importProviders,
} from "../../../api/documents";
import type { AIProvider, ArenaRating, ProvidersExport } from "../../../types";
import { ProviderSection } from "./ai/ProviderSection";

// ── Main AITab ────────────────────────────────────────────────────────────────

export function AITab() {
  const { t } = useT();
  const ai = t.admin.ai;

  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [ratings, setRatings] = useState<Record<string, ArenaRating>>({});
  const [visionEnabled, setVisionEnabled] = useState(false);
  const [togglingVision, setTogglingVision] = useState(false);
  const [updatingRatings, setUpdatingRatings] = useState(false);
  const [ratingsMsg, setRatingsMsg] = useState("");
  const [ioMsg, setIoMsg] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = () => listProviders().then(setProviders).catch(() => {});

  useEffect(() => {
    load();
    getAppSettings()
      .then(s => setVisionEnabled(s["enable_ai_vision"] === "true"))
      .catch(() => {});
    getArenaRatings().then(setRatings).catch(() => {});
  }, []);

  const handleVisionToggle = async () => {
    setTogglingVision(true);
    const next = !visionEnabled;
    try {
      await updateAppSettings({ enable_ai_vision: next ? "true" : "false" });
      setVisionEnabled(next);
    } finally {
      setTogglingVision(false);
    }
  };

  const handleUpdateRatings = async () => {
    setUpdatingRatings(true);
    setRatingsMsg("");
    try {
      const res = await refreshArenaRatings();
      setRatings(res.ratings);
      setRatingsMsg(`${ai.ratingsUpdated} (${res.updated})`);
    } catch {
      setRatingsMsg("Failed — check connection");
    } finally {
      setUpdatingRatings(false);
    }
  };

  const handleExport = async () => {
    setIoMsg("");
    try {
      const data = await exportProviders();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `docintel-ai-providers-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setIoMsg(t.error);
    }
  };

  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-importing the same file
    if (!file) return;
    setIoMsg("");
    try {
      const parsed = JSON.parse(await file.text()) as ProvidersExport;
      if (!parsed?.providers?.length) { setIoMsg(t.error); return; }
      const replace = window.confirm(ai.importReplace);
      const res = await importProviders({ providers: parsed.providers, replace });
      setIoMsg(ai.imported.replace("{{n}}", String(res.imported)));
      load();
    } catch {
      setIoMsg(t.error);
    }
  };

  const analysisProviders = providers.filter(p => p.task_type === "analysis" || p.task_type === "both");
  const visionProviders   = providers.filter(p => p.task_type === "vision"   || p.task_type === "both");
  const premiumProviders  = providers.filter(p => p.task_type === "premium");

  return (
    <div className="admin-section">
      {/* Header row: title + Update Ratings button */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <h3 className="admin-section-title">{ai.title}</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {(ratingsMsg || ioMsg) && <span className="text-xs text-muted">{ioMsg || ratingsMsg}</span>}
          <Button variant="ghost" size="sm" icon={<Download size={13} />} onClick={handleExport}>
            {ai.exportConfig}
          </Button>
          <Button variant="ghost" size="sm" icon={<Upload size={13} />} onClick={() => fileInputRef.current?.click()}>
            {ai.importConfig}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            style={{ display: "none" }}
            onChange={handleImportFile}
          />
          <Button
            variant="ghost"
            size="sm"
            icon={<RefreshCw size={13} />}
            loading={updatingRatings}
            onClick={handleUpdateRatings}
          >
            {updatingRatings ? ai.updatingRatings : ai.updateRatings}
          </Button>
        </div>
      </div>
      <p className="text-xs text-muted" style={{ marginTop: -4 }}>{ai.exportWarning}</p>

      {/* Vision global toggle */}
      <div className="provider-item" style={{ marginBottom: 4 }}>
        <div>
          <span className="provider-name">{ai.enableVision}</span>
          <p className="text-xs text-muted" style={{ marginTop: 2 }}>{ai.visionHint}</p>
        </div>
        <label className="toggle-switch" title={visionEnabled ? t.enabled : t.disabled}>
          <input
            type="checkbox"
            checked={visionEnabled}
            onChange={handleVisionToggle}
            disabled={togglingVision}
          />
          <span className="toggle-slider" />
        </label>
      </div>

      {/* Analysis providers */}
      <ProviderSection
        title={ai.analysisProviders}
        hint={ai.analysisHint}
        providers={analysisProviders}
        taskType="analysis"
        ratings={ratings}
        onReload={load}
      />

      {/* Vision providers */}
      <ProviderSection
        title={ai.visionProviders}
        hint={ai.visionHint2}
        providers={visionProviders}
        taskType="vision"
        ratings={ratings}
        onReload={load}
      />

      {/* Premium vision (judge) providers */}
      <ProviderSection
        title={ai.premiumProviders}
        hint={ai.premiumHint}
        providers={premiumProviders}
        taskType="premium"
        ratings={ratings}
        onReload={load}
      />
    </div>
  );
}
