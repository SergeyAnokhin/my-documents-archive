import { useState, useEffect } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import {
  listProviders,
  getArenaRatings, refreshArenaRatings,
  getAppSettings, updateAppSettings,
} from "../../../api/documents";
import type { AIProvider, ArenaRating } from "../../../types";
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

  const analysisProviders = providers.filter(p => p.task_type === "analysis" || p.task_type === "both");
  const visionProviders   = providers.filter(p => p.task_type === "vision"   || p.task_type === "both");
  const premiumProviders  = providers.filter(p => p.task_type === "premium");

  return (
    <div className="admin-section">
      {/* Header row: title + Update Ratings button */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <h3 className="admin-section-title">{ai.title}</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {ratingsMsg && <span className="text-xs text-muted">{ratingsMsg}</span>}
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

      {/* Vision global toggle */}
      <div className="provider-item" style={{ marginBottom: 4 }}>
        <div>
          <span className="provider-name">{ai.enableVision}</span>
          <p className="text-xs text-muted" style={{ marginTop: 2 }}>{ai.visionHint}</p>
        </div>
        <button className="icon-btn" onClick={handleVisionToggle} disabled={togglingVision}
          title={visionEnabled ? t.enabled : t.disabled}>
          <span className={`status-dot ${visionEnabled ? "done" : "pending"}`} />
        </button>
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
