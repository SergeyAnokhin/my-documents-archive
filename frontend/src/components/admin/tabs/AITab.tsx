import { useState, useEffect, useMemo } from "react";
import { ChevronUp, ChevronDown, Plus, Trash2, RefreshCw } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import {
  listProviders, addProvider, toggleProvider, removeProvider,
  updateProviderOrder, fetchProviderModels,
  getArenaRatings, refreshArenaRatings,
  getAppSettings, updateAppSettings,
} from "../../../api/documents";
import type { AIProvider, ProviderModel, ArenaRating } from "../../../types";

// ── Constants ─────────────────────────────────────────────────────────────────

const PROVIDER_TYPES = [
  { value: "anthropic",  label: "Anthropic (Claude)" },
  { value: "openai",     label: "OpenAI" },
  { value: "gemini",     label: "Google Gemini" },
  { value: "deepseek",   label: "DeepSeek" },
  { value: "openrouter", label: "OpenRouter" },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtTokens(n: number): string {
  if (n === 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

function fmtCtx(n?: number | null): string {
  if (!n) return "";
  if (n >= 1_000_000) return `${Math.round(n / 1_000_000)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

/** Cost for analysis tasks: 75% input + 25% output (typical chat distribution). */
function blendedPrice(price_in?: number | null, price_out?: number | null): string {
  if (price_in == null) return "?";
  if (price_in === 0) return "free";
  const blended = price_in * 0.75 + (price_out ?? price_in) * 0.25;
  return `$${blended < 0.01 ? blended.toFixed(4) : blended.toFixed(2)}`;
}

/** Cost for vision tasks: show input price (image tokens are input-heavy). */
function inputPrice(price_in?: number | null): string {
  if (price_in == null) return "?";
  if (price_in === 0) return "free";
  return `$${price_in < 0.01 ? price_in.toFixed(4) : price_in.toFixed(2)}`;
}

/** Lookup rating by model id: try exact match, then partial (e.g. "openai/gpt-4o" → "gpt-4o"). */
function lookupRating(
  ratings: Record<string, ArenaRating>,
  modelId: string,
  forVision: boolean,
): number {
  const normalised = modelId.toLowerCase();
  const direct = ratings[normalised];
  if (direct) return forVision ? direct.vision : direct.text;
  // Try short model name (last segment of provider/model)
  const short = normalised.split("/").pop() ?? "";
  const shortMatch = ratings[short];
  if (shortMatch) return forVision ? shortMatch.vision : shortMatch.text;
  return 0;
}

function Stars({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span style={{ fontSize: 11, color: "#f59e0b", letterSpacing: 1, flexShrink: 0 }} title={`${count}/5 stars`}>
      {"★".repeat(count)}{"☆".repeat(5 - count)}
    </span>
  );
}

// ── Model picker with search ──────────────────────────────────────────────────

function ModelPicker({
  models,
  selected,
  ratings,
  forVision,
  onSelect,
}: {
  models: ProviderModel[];
  selected: string;
  ratings: Record<string, ArenaRating>;
  forVision: boolean;
  onSelect: (m: ProviderModel) => void;
}) {
  const { t } = useT();
  const ai = t.admin.ai;
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    const base = forVision ? models.filter(m => m.supports_vision) : models;
    return q ? base.filter(m => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)) : base;
  }, [models, query, forVision]);

  return (
    <div>
      <input
        className="admin-input"
        placeholder={ai.searchModels}
        value={query}
        onChange={e => setQuery(e.target.value)}
        style={{ marginBottom: 6 }}
      />
      {filtered.length === 0 ? (
        <p className="text-xs text-muted">{forVision ? "No vision-capable models found" : ai.noModels}</p>
      ) : (
        <div style={{
          border: "1.5px solid var(--color-border)",
          borderRadius: 6,
          maxHeight: 240,
          overflowY: "auto",
        }}>
          {filtered.map(m => {
            const stars = lookupRating(ratings, m.id, forVision);
            const priceStr = forVision ? inputPrice(m.price_in) : blendedPrice(m.price_in, m.price_out);
            const isSelected = selected === m.id;

            return (
              <div
                key={m.id}
                onClick={() => onSelect(m)}
                style={{
                  padding: "7px 10px",
                  cursor: "pointer",
                  borderBottom: "1px solid var(--color-border-soft)",
                  background: isSelected ? "var(--color-accent-subtle, #f0f0ff)" : "transparent",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                {/* Free badge */}
                {m.is_free && (
                  <span style={{
                    fontSize: 9, fontWeight: 700, padding: "1px 4px",
                    borderRadius: 3, background: "#16a34a", color: "#fff", flexShrink: 0,
                  }}>FREE</span>
                )}
                {/* Vision badge */}
                {m.supports_vision && !forVision && (
                  <span style={{
                    fontSize: 9, fontWeight: 700, padding: "1px 4px",
                    borderRadius: 3, background: "#6366f1", color: "#fff", flexShrink: 0,
                  }}>{ai.visionBadge}</span>
                )}
                {/* Model name */}
                <span style={{ flex: 1, fontSize: 12.5, fontWeight: isSelected ? 600 : 400, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {m.name !== m.id ? m.name : m.id}
                </span>
                {/* Stars */}
                <Stars count={stars} />
                {/* Price + context */}
                <span className="text-xs text-muted" style={{ flexShrink: 0, textAlign: "right", fontSize: 11 }}>
                  {priceStr}{m.context_length ? ` · ${fmtCtx(m.context_length)}` : ""}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Add Provider form ─────────────────────────────────────────────────────────

interface FormState {
  provider_type: string;
  api_key: string;
  base_url: string;
  model: string;
  key_name: string;
  name: string;
}

const EMPTY_FORM: FormState = {
  provider_type: "anthropic",
  api_key: "",
  base_url: "",
  model: "",
  key_name: "",
  name: "",
};

function autoName(providerType: string, modelId: string, keyName: string): string {
  const base = modelId ? `${providerType}/${modelId}` : providerType;
  return keyName ? `${base} [${keyName}]` : base;
}

function defaultKeyName(apiKey: string): string {
  return apiKey.length >= 5 ? `…${apiKey.slice(-5)}` : apiKey;
}

function AddProviderForm({
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
  const forVision = taskType === "vision" || taskType === "premium";

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [models, setModels] = useState<ProviderModel[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [saving, setSaving] = useState(false);

  const showBaseUrl = form.provider_type === "openai";

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
      {/* Provider type */}
      <select
        className="admin-input"
        value={form.provider_type}
        onChange={e => setForm(f => ({ ...f, provider_type: e.target.value, model: "", name: "" }))}
      >
        {PROVIDER_TYPES.map(pt => (
          <option key={pt.value} value={pt.value}>{pt.label}</option>
        ))}
      </select>

      {/* API key */}
      <input
        className="admin-input"
        placeholder={ai.apiKey}
        type="password"
        value={form.api_key}
        onChange={e => setForm(f => ({ ...f, api_key: e.target.value, name: f.model ? autoName(f.provider_type, f.model, f.key_name || defaultKeyName(e.target.value)) : "" }))}
      />

      {/* Key label */}
      <input
        className="admin-input"
        placeholder={ai.keyName}
        value={form.key_name}
        onChange={e => {
          const kn = e.target.value;
          setForm(f => ({ ...f, key_name: kn, name: f.model ? autoName(f.provider_type, f.model, kn || defaultKeyName(f.api_key)) : "" }));
        }}
      />

      {/* Optional base URL */}
      {showBaseUrl && (
        <input
          className="admin-input"
          placeholder={ai.baseUrlPlaceholder}
          value={form.base_url}
          onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))}
        />
      )}

      {/* Fetch models */}
      <Button
        variant="secondary"
        size="sm"
        loading={loadingModels}
        disabled={!form.api_key}
        onClick={handleFetchModels}
      >
        {loadingModels ? ai.fetchingModels : ai.fetchModels}
      </Button>

      {/* Model picker */}
      {models.length > 0 && (
        <ModelPicker
          models={models}
          selected={form.model}
          ratings={ratings}
          forVision={forVision}
          onSelect={handleSelectModel}
        />
      )}

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
    </div>
  );
}

// ── Provider row ──────────────────────────────────────────────────────────────

function ProviderRow({
  provider,
  isFirst,
  isLast,
  onToggle,
  onDelete,
  onMoveUp,
  onMoveDown,
}: {
  provider: AIProvider;
  isFirst: boolean;
  isLast: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  const { t } = useT();
  const ai = t.admin.ai;
  const hasStats = provider.total_tokens_in > 0 || provider.total_tokens_out > 0;

  return (
    <li className="provider-item" style={{ alignItems: "flex-start", gap: 6 }}>
      {/* Priority arrows */}
      <div style={{ display: "flex", flexDirection: "column", gap: 1, paddingTop: 2, flexShrink: 0 }}>
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
          <div className="text-xs text-muted" style={{ marginTop: 2 }}>
            {fmtTokens(provider.total_tokens_in)} {ai.tokensIn} ·{" "}
            {fmtTokens(provider.total_tokens_out)} {ai.tokensOut} ·{" "}
            ${provider.total_cost_usd.toFixed(4)}
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="folder-actions" style={{ flexShrink: 0 }}>
        <button className="icon-btn" onClick={onToggle} title={provider.enabled ? t.enabled : t.disabled}>
          <span className={`status-dot ${provider.enabled ? "done" : "pending"}`} />
        </button>
        <button className="icon-btn" onClick={onDelete} title={t.delete}>
          <Trash2 size={14} />
        </button>
      </div>
    </li>
  );
}

// ── Provider section ──────────────────────────────────────────────────────────

function ProviderSection({
  title,
  hint,
  providers,
  taskType,
  ratings,
  onReload,
}: {
  title: string;
  hint: string;
  providers: AIProvider[];
  taskType: "analysis" | "vision" | "premium";
  ratings: Record<string, ArenaRating>;
  onReload: () => void;
}) {
  const { t } = useT();
  const [showForm, setShowForm] = useState(false);

  const moveProvider = async (index: number, direction: "up" | "down") => {
    const swapIndex = direction === "up" ? index - 1 : index + 1;
    if (swapIndex < 0 || swapIndex >= providers.length) return;
    const a = providers[index];
    const b = providers[swapIndex];
    const orderA = a.sort_order !== b.sort_order ? a.sort_order : index * 10;
    const orderB = a.sort_order !== b.sort_order ? b.sort_order : swapIndex * 10;
    await updateProviderOrder(a.id, orderB);
    await updateProviderOrder(b.id, orderA);
    onReload();
  };

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{title}</span>
        <p className="text-xs text-muted" style={{ marginTop: 2 }}>{hint}</p>
      </div>

      {providers.length === 0 ? (
        <p className="text-muted" style={{ fontSize: 13, marginBottom: 8 }}>
          {t.admin.ai.noProviders}
        </p>
      ) : (
        <ul className="provider-list">
          {providers.map((p, i) => (
            <ProviderRow
              key={p.id}
              provider={p}
              isFirst={i === 0}
              isLast={i === providers.length - 1}
              onToggle={() => toggleProvider(p.id).then(onReload)}
              onDelete={() => removeProvider(p.id).then(onReload)}
              onMoveUp={() => moveProvider(i, "up")}
              onMoveDown={() => moveProvider(i, "down")}
            />
          ))}
        </ul>
      )}

      {!showForm ? (
        <Button variant="secondary" size="sm" icon={<Plus size={14} />}
          onClick={() => setShowForm(true)} style={{ marginTop: 4 }}>
          {t.admin.ai.addProvider}
        </Button>
      ) : (
        <AddProviderForm
          taskType={taskType}
          ratings={ratings}
          onSaved={() => { setShowForm(false); onReload(); }}
          onCancel={() => setShowForm(false)}
        />
      )}
    </div>
  );
}

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
