import { useState } from "react";
import { Button } from "../../../ui/Button";
import { Modal } from "../../../ui/Modal";
import { useT } from "../../../../i18n";
import { fetchProviderModels, addProvider } from "../../../../api/documents";
import type { ProviderModel, ArenaRating } from "../../../../types";
import { PROVIDER_TYPES, OPENROUTER_BASE_URL, autoName, defaultKeyName } from "./aiUtils";
import { ModelPicker } from "./ModelPicker";

interface FormState {
  provider_type: string;
  api_key: string;
  base_url: string;
  model: string;
  key_name: string;
  name: string;
}

const EMPTY_FORM: FormState = {
  provider_type: "gemini",
  api_key: "",
  base_url: "",
  model: "",
  key_name: "",
  name: "",
};

export function AddProviderForm({
  taskType,
  ratings,
  onSaved,
  onCancel,
}: {
  taskType: "analysis" | "vision" | "premium";
  ratings: Record<string, ArenaRating>;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { t } = useT();
  const ai = t.admin.ai;
  const forVision = taskType === "vision";

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showModelModal, setShowModelModal] = useState(false);

  const showBaseUrl = ["openai", "mistral"].includes(form.provider_type);

  const handleFetchModels = async () => {
    setLoadingModels(true);
    setModels([]);
    try {
      const list = await fetchProviderModels({
        provider_type: form.provider_type,
        api_key: form.api_key,
        base_url: form.base_url || undefined,
      });
      setModels(list);
      if (list.length > 0) setShowModelModal(true);
    } finally {
      setLoadingModels(false);
    }
  };

  const handleSelectModel = (m: ProviderModel) => {
    const kn = form.key_name || defaultKeyName(form.api_key);
    setForm(f => ({
      ...f,
      model: m.id,
      name: autoName(f.provider_type, m.id, kn),
    }));
    setShowModelModal(false);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const kn = form.key_name || (form.api_key ? defaultKeyName(form.api_key) : undefined);
      await addProvider({
        name: form.name || undefined,
        provider_type: form.provider_type,
        api_key: form.api_key,
        base_url: form.base_url || undefined,
        model: form.model || undefined,
        task_type: taskType,
        key_name: kn || undefined,
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="provider-form" style={{ marginTop: 8 }}>
      {/* Row 1: Provider type + API key + Key name in one line */}
      <div style={{ display: "grid", gridTemplateColumns: "minmax(110px,1fr) minmax(140px,2fr) minmax(110px,1fr)", gap: 8 }}>
        <select
          className="admin-input"
          value={form.provider_type}
          onChange={e => {
            const pt = e.target.value;
            setForm(f => ({
              ...f,
              provider_type: pt,
              model: "",
              name: "",
              base_url: pt === "openrouter" ? OPENROUTER_BASE_URL : "",
            }));
          }}
        >
          {PROVIDER_TYPES.map(pt => (
            <option key={pt.value} value={pt.value}>{pt.label}</option>
          ))}
        </select>
        <input
          className="admin-input"
          placeholder={ai.apiKey}
          type="password"
          value={form.api_key}
          onChange={e => setForm(f => ({ ...f, api_key: e.target.value, name: f.model ? autoName(f.provider_type, f.model, f.key_name || defaultKeyName(e.target.value)) : "" }))}
        />
        <input
          className="admin-input"
          placeholder={ai.keyName}
          value={form.key_name}
          onChange={e => {
            const kn = e.target.value;
            setForm(f => ({ ...f, key_name: kn, name: f.model ? autoName(f.provider_type, f.model, kn || defaultKeyName(f.api_key)) : "" }));
          }}
        />
      </div>

      {/* Optional base URL */}
      {showBaseUrl && (
        <input
          className="admin-input"
          placeholder={ai.baseUrlPlaceholder}
          value={form.base_url}
          onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))}
        />
      )}

      {/* Fetch models + selected model chip */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <Button
          variant="secondary"
          size="sm"
          loading={loadingModels}
          disabled={!form.api_key}
          onClick={handleFetchModels}
        >
          {loadingModels ? ai.fetchingModels : ai.fetchModels}
        </Button>
        {form.model && (
          <button
            onClick={() => models.length > 0 && setShowModelModal(true)}
            style={{
              fontSize: 11, fontFamily: "monospace", color: "var(--color-ink-muted)",
              background: "var(--color-tag)", border: "none", borderRadius: 4,
              padding: "3px 8px", cursor: models.length > 0 ? "pointer" : "default",
            }}
            title={models.length > 0 ? ai.selectModel : undefined}
          >
            {form.model}
          </button>
        )}
      </div>

      {/* Provider name (auto-filled, editable) */}
      <input
        className="admin-input"
        placeholder={ai.providerName}
        value={form.name}
        onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
      />

      <div style={{ display: "flex", gap: 8 }}>
        <Button variant="primary" size="sm" loading={saving} disabled={!form.api_key} onClick={handleSave}>
          {t.save}
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>{t.cancel}</Button>
      </div>

      {/* Model picker modal */}
      <Modal open={showModelModal} onClose={() => setShowModelModal(false)} title={ai.selectModel} size="md">
        <ModelPicker
          models={models}
          selected={form.model}
          ratings={ratings}
          forVision={forVision}
          onSelect={handleSelectModel}
        />
      </Modal>
    </div>
  );
}
