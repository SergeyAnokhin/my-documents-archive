import { useState, useEffect } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import {
  listProviders, addProvider, toggleProvider, removeProvider,
  getAppSettings, updateAppSettings,
} from "../../../api/documents";
import type { AIProvider } from "../../../types";

const EMPTY_FORM = { name: "", provider_type: "anthropic", api_key: "", base_url: "", model: "" };

export function AITab() {
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
