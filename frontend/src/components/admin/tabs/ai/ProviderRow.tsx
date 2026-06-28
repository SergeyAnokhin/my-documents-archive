import { useState } from "react";
import { ChevronUp, ChevronDown, Trash2, Pencil, Settings } from "lucide-react";
import { Button } from "../../../ui/Button";
import { Modal } from "../../../ui/Modal";
import { useT } from "../../../../i18n";
import { fetchProviderModelsById, updateProviderModel, updateProviderSettings } from "../../../../api/documents";
import type { AIProvider, ProviderModel, ArenaRating } from "../../../../types";
import { fmtTokens } from "./aiUtils";
import { ModelPicker } from "./ModelPicker";
import { ProviderSettingsPanel } from "./ProviderSettingsPanel";

export function ProviderRow({
  provider,
  isFirst,
  isLast,
  ratings,
  forVision,
  onToggle,
  onDelete,
  onMoveUp,
  onMoveDown,
  onReload,
}: {
  provider: AIProvider;
  isFirst: boolean;
  isLast: boolean;
  ratings: Record<string, ArenaRating>;
  forVision: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onReload: () => void;
}) {
  const { t } = useT();
  const ai = t.admin.ai;
  const hasStats = provider.total_tokens_in > 0 || provider.total_tokens_out > 0;

  const [editOpen, setEditOpen] = useState(false);
  const [editModels, setEditModels] = useState<ProviderModel[]>([]);
  const [loadingEdit, setLoadingEdit] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pendingModel, setPendingModel] = useState<string | null>(null);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [pendingSettings, setPendingSettings] = useState<Record<string, unknown>>({});
  const [savingSettings, setSavingSettings] = useState(false);

  const openEdit = async () => {
    setPendingModel(null);
    setLoadingEdit(true);
    setEditOpen(true);
    try {
      const list = await fetchProviderModelsById(provider.id);
      setEditModels(list);
    } catch {
      setEditModels([]);
    } finally {
      setLoadingEdit(false);
    }
  };

  const saveModel = async () => {
    if (!pendingModel) return;
    setSaving(true);
    try {
      await updateProviderModel(provider.id, pendingModel);
      onReload();
      setEditOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const handleSelectEditModel = (m: ProviderModel) => {
    setPendingModel(m.id);
  };

  const openSettings = () => {
    setPendingSettings({ ...(provider.extra_params ?? {}) });
    setSettingsOpen(true);
  };

  const saveSettings = async () => {
    setSavingSettings(true);
    try {
      const cleaned = Object.fromEntries(
        Object.entries(pendingSettings).filter(([, v]) => v !== undefined && v !== null && v !== "")
      );
      await updateProviderSettings(provider.id, cleaned);
      onReload();
      setSettingsOpen(false);
    } finally {
      setSavingSettings(false);
    }
  };

  return (
    <li className="provider-item" style={{ alignItems: "flex-start", gap: 6, flexDirection: "column", padding: "5px 8px" }}>
      <div style={{ display: "flex", width: "100%", alignItems: "center", gap: 4 }}>
        {/* Priority arrows — horizontal to keep card single-line */}
        <div style={{ display: "flex", flexDirection: "row", gap: 1, flexShrink: 0 }}>
          <button className="icon-btn" onClick={onMoveUp} disabled={isFirst} title={ai.moveUp}
            style={{ opacity: isFirst ? 0.25 : 1 }}>
            <ChevronUp size={13} />
          </button>
          <button className="icon-btn" onClick={onMoveDown} disabled={isLast} title={ai.moveDown}
            style={{ opacity: isLast ? 0.25 : 1 }}>
            <ChevronDown size={13} />
          </button>
        </div>

        {/* Info */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <span className="provider-name" style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {provider.name}
          </span>
          {hasStats && (
            <div className="text-xs text-muted" style={{ marginTop: 1 }}>
              {fmtTokens(provider.total_tokens_in)} {ai.tokensIn} ·{" "}
              {fmtTokens(provider.total_tokens_out)} {ai.tokensOut} ·{" "}
              ${provider.total_cost_usd.toFixed(4)}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="folder-actions" style={{ flexShrink: 0 }}>
          <button className="icon-btn" onClick={openEdit} title="Сменить модель" style={{ color: editOpen ? "var(--color-accent)" : undefined }}>
            <Pencil size={13} />
          </button>
          <button className="icon-btn" onClick={openSettings} title={ai.providerSettings} style={{ color: settingsOpen ? "var(--color-accent)" : undefined }}>
            <Settings size={13} />
          </button>
          <label className="toggle-switch" title={provider.enabled ? t.enabled : t.disabled} style={{ flexShrink: 0 }}>
            <input type="checkbox" checked={provider.enabled} onChange={onToggle} />
            <span className="toggle-slider" />
          </label>
          <button className="icon-btn" onClick={onDelete} title={t.delete}>
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Model picker modal */}
      <Modal open={editOpen} onClose={() => setEditOpen(false)} title={ai.selectModel} size="md">
        {loadingEdit ? (
          <p className="text-xs text-muted">{ai.fetchingModels}</p>
        ) : editModels.length === 0 ? (
          <p className="text-xs text-muted">{ai.noModels}</p>
        ) : (
          <>
            <ModelPicker
              models={editModels}
              selected={pendingModel ?? provider.model ?? ""}
              ratings={ratings}
              forVision={forVision}
              onSelect={handleSelectEditModel}
            />
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <Button variant="primary" size="sm" loading={saving} disabled={!pendingModel || saving} onClick={saveModel}>
                {t.save}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setEditOpen(false)}>{t.cancel}</Button>
            </div>
          </>
        )}
      </Modal>

      {/* Provider settings modal */}
      <Modal open={settingsOpen} onClose={() => setSettingsOpen(false)} title={ai.providerSettings} size="sm">
        <ProviderSettingsPanel
          providerType={provider.provider_type}
          settings={pendingSettings}
          onChange={(key, value) => setPendingSettings(prev => ({ ...prev, [key]: value }))}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <Button variant="primary" size="sm" loading={savingSettings} disabled={savingSettings} onClick={saveSettings}>
            {t.save}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setSettingsOpen(false)}>{t.cancel}</Button>
        </div>
      </Modal>
    </li>
  );
}
