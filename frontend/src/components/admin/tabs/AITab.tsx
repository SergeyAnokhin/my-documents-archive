import { useState, useEffect, useMemo } from "react";
import { ChevronUp, ChevronDown, Plus, Trash2, RefreshCw, Pencil } from "lucide-react";
import { Button } from "../../ui/Button";
import { Modal } from "../../ui/Modal";
import { useT } from "../../../i18n";
import {
  listProviders, addProvider, toggleProvider, removeProvider,
  updateProviderOrder, fetchProviderModels, fetchProviderModelsById,
  updateProviderModel,
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
  { value: "mistral",    label: "Mistral" },
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

/** Lookup rating by model id: exact → short segment → Gemini family prefix match. */
function lookupRating(
  ratings: Record<string, ArenaRating>,
  modelId: string,
  forVision: boolean,
): number {
  const pick = (r: ArenaRating) => forVision ? r.vision : r.text;
  const normalised = modelId.toLowerCase();

  const direct = ratings[normalised];
  if (direct) return pick(direct);

  // "openai/gpt-4o" → "gpt-4o"
  const short = normalised.split("/").pop() ?? "";
  const shortMatch = ratings[short];
  if (shortMatch) return pick(shortMatch);

  // Gemini family prefix match: "gemini-3.1-flash-lite-preview" → try "gemini-2.5-flash-lite"
  if (normalised.startsWith("gemini-")) {
    const isProModel = normalised.includes("-pro");
    const isFlashLite = normalised.includes("flash-lite") || normalised.includes("flash-8b");
    const isFlash = normalised.includes("flash") && !isFlashLite;
    const family = isProModel ? "gemini-2.5-pro" : isFlashLite ? "gemini-2.5-flash-lite" : isFlash ? "gemini-2.5-flash" : null;
    if (family && ratings[family]) return pick(ratings[family]);
  }
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

// ── Model picker with search and sort ────────────────────────────────────────

type SortKey = "default" | "rating" | "price";

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
  const [sortBy, setSortBy] = useState<SortKey>("default");

  const priceKey = (m: ProviderModel) => {
    if (m.is_free) return -1;
    if (m.price_in == null) return Infinity;
    return m.price_in * 0.75 + (m.price_out ?? m.price_in) * 0.25;
  };

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    const base = forVision ? models.filter(m => m.supports_vision) : models;
    let result = q ? base.filter(m => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)) : base;
    if (sortBy === "rating") {
      result = [...result].sort((a, b) => lookupRating(ratings, b.id, forVision) - lookupRating(ratings, a.id, forVision));
    } else if (sortBy === "price") {
      result = [...result].sort((a, b) => priceKey(a) - priceKey(b));
    }
    return result;
  }, [models, query, forVision, sortBy, ratings]);

  const sortBtn = (key: SortKey, label: string, title: string) => (
    <button
      key={key}
      title={title}
      onClick={() => setSortBy(key)}
      style={{
        padding: "4px 9px",
        borderRadius: 4,
        border: "1.5px solid var(--color-border)",
        background: sortBy === key ? "var(--color-accent)" : "var(--color-surface)",
        color: sortBy === key ? "var(--color-accent-fg)" : "var(--color-ink-muted)",
        fontSize: 12,
        cursor: "pointer",
        flexShrink: 0,
        fontWeight: sortBy === key ? 700 : 400,
        lineHeight: 1.4,
      }}
    >
      {label}
    </button>
  );

  return (
    <div>
      <div style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
        <input
          className="admin-input"
          placeholder={ai.searchModels}
          value={query}
          onChange={e => setQuery(e.target.value)}
          style={{ flex: 1 }}
        />
        {sortBtn("default", "—", ai.sortDefault ?? "По умолчанию")}
        {sortBtn("rating", "★", ai.sortRating ?? "По рейтингу")}
        {sortBtn("price", "$", ai.sortPrice ?? "По цене")}
      </div>
      {filtered.length === 0 ? (
        <p className="text-xs text-muted">{forVision ? "No vision-capable models found" : ai.noModels}</p>
      ) : (
        <div style={{
          border: "1.5px solid var(--color-border)",
          borderRadius: 6,
          maxHeight: 340,
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
                  padding: "5px 8px",
                  cursor: "pointer",
                  borderBottom: "1px solid var(--color-border-soft)",
                  background: isSelected ? "var(--color-tag)" : "transparent",
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                }}
              >
                {m.is_free && (
                  <span style={{
                    fontSize: 8, fontWeight: 700, padding: "1px 3px",
                    borderRadius: 3, background: "#16a34a", color: "#fff", flexShrink: 0,
                  }}>FREE</span>
                )}
                {m.supports_vision && !forVision && (
                  <span style={{
                    fontSize: 8, fontWeight: 700, padding: "1px 3px",
                    borderRadius: 3, background: "#6366f1", color: "#fff", flexShrink: 0,
                  }}>{ai.visionBadge}</span>
                )}
                <span style={{ flex: 1, fontSize: 12, fontWeight: isSelected ? 600 : 400, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {m.name !== m.id ? m.name : m.id}
                </span>
                <Stars count={stars} />
                <span className="text-xs text-muted" style={{ flexShrink: 0, textAlign: "right", fontSize: 10.5 }}>
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
  const [showModelModal, setShowModelModal] = useState(false);

  const showBaseUrl = ["openai", "mistral", "openrouter"].includes(form.provider_type);

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
          onChange={e => setForm(f => ({ ...f, provider_type: e.target.value, model: "", name: "" }))}
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

// ── Provider row ──────────────────────────────────────────────────────────────

function ProviderRow({
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
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleSelectEditModel = (m: ProviderModel) => {
    setPendingModel(m.id);
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
          <button className="icon-btn" onClick={onToggle} title={provider.enabled ? t.enabled : t.disabled}>
            <span className={`status-dot ${provider.enabled ? "done" : "pending"}`} />
          </button>
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
              ratings={ratings}
              forVision={taskType === "vision" || taskType === "premium"}
              onToggle={() => toggleProvider(p.id).then(onReload)}
              onDelete={() => removeProvider(p.id).then(onReload)}
              onMoveUp={() => moveProvider(i, "up")}
              onMoveDown={() => moveProvider(i, "down")}
              onReload={onReload}
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
