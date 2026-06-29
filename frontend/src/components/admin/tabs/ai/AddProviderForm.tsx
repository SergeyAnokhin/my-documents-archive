import { useState } from "react";
import { Button } from "../../../ui/Button";
import { Modal } from "../../../ui/Modal";
import { useT } from "../../../../i18n";
import { fetchProviderModels, addProvider } from "../../../../api/documents";
import type { ProviderModel, ArenaRating } from "../../../../types";
import { PROVIDER_TYPES, OPENROUTER_BASE_URL, autoName, defaultKeyName } from "./aiUtils";
import { ModelPicker } from "./ModelPicker";
import { chatgptOAuth } from "../../../../api/chatgpt";

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

  // ── OAuth state ──────────────────────────────────────────────────────────
  const [oauthStep, setOAuthStep] = useState<"idle" | "waiting" | "authorized" | "error">("idle");
  const [oauthDeviceCode, setOAuthDeviceCode] = useState<{
    device_auth_id: string;
    user_code: string;
    verification_uri: string;
    interval: number;
  } | null>(null);
  const [oauthMessage, setOAuthMessage] = useState("");
  const [oauthTokens, setOAuthTokens] = useState<{
    access_token: string;
    refresh_token: string;
    expires_at: number;
  } | null>(null);

  const showBaseUrl = ["openai", "mistral"].includes(form.provider_type);
  const isChatGPTWeb = form.provider_type === "openai_web";

  // ── OAuth: start device code flow ────────────────────────────────────────
  const handleStartOAuth = async () => {
    setOAuthStep("waiting");
    setOAuthMessage("Requesting device code...");
    try {
      const dc = await chatgptOAuth.startDeviceCode();
      setOAuthDeviceCode(dc);
      setOAuthMessage(`Go to ${dc.verification_uri} and enter code: ${dc.user_code}`);
      // Start polling
      pollForToken(dc.device_auth_id, dc.user_code, dc.interval);
    } catch (e: any) {
      setOAuthStep("error");
      setOAuthMessage(e?.message || String(e));
    }
  };

  const pollForToken = async (device_auth_id: string, user_code: string, interval: number) => {
    const maxAttempts = Math.ceil(900 / Math.max(interval, 3)); // 900s timeout
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise(r => setTimeout(r, Math.max(interval, 3) * 1000));
      try {
        const result = await chatgptOAuth.pollToken(
          device_auth_id,
          user_code,
          interval,
          0,
        );
        if (result.status === "authorized") {
          setOAuthStep("authorized");
          setOAuthMessage("Connected! Select a model and save.");
          // Store tokens for later save
          const expiresAt = Date.now() / 1000 + (result.expires_in || 3600) - 120;
          setOAuthTokens({
            access_token: result.access_token,
            refresh_token: result.refresh_token,
            expires_at: expiresAt,
          });
          setForm(f => ({ ...f, api_key: result.access_token }));
          // Auto-fetch models
          await handleFetchModelsForOAuth(result.access_token);
          return;
        }
        if (result.status === "expired") {
          setOAuthStep("error");
          setOAuthMessage("Code expired. Please try again.");
          return;
        }
        if (result.status === "denied") {
          setOAuthStep("error");
          setOAuthMessage("Authorization declined.");
          return;
        }
        if (result.status === "error") {
          setOAuthStep("error");
          setOAuthMessage(result.message || "Unknown error");
          return;
        }
        // "pending" — continue polling
        setOAuthMessage(`Waiting for authorization... (code: ${oauthDeviceCode?.user_code || "?"})`);
      } catch (e: any) {
        setOAuthStep("error");
        setOAuthMessage(e?.message || String(e));
        return;
      }
    }
    setOAuthStep("error");
    setOAuthMessage("Timed out waiting for authorization.");
  };

  // ── Internal: fetch models with OAuth access token ──────────────────────
  const handleFetchModelsForOAuth = async (apiKey: string) => {
    setLoadingModels(true);
    setModels([]);
    try {
      const list = await fetchProviderModels({
        provider_type: form.provider_type,
        api_key: apiKey,
        base_url: undefined,
      });
      setModels(list);
      if (list.length > 0) setShowModelModal(true);
    } finally {
      setLoadingModels(false);
    }
  };

  // ── Save provider with OAuth tokens ─────────────────────────────────────
  const handleSaveOAuth = async () => {
    setSaving(true);
    try {
      const kn = form.key_name || "ChatGPT";
      const extraParams = oauthTokens ? {
        oauth: {
          refresh_token: oauthTokens.refresh_token,
          expires_at: oauthTokens.expires_at,
          token_type: "Bearer",
        },
      } : undefined;
      await addProvider({
        name: form.name || autoName(form.provider_type, form.model || "gpt-4o-mini", kn),
        provider_type: form.provider_type,
        api_key: form.api_key,
        base_url: undefined,
        model: form.model || "gpt-4o-mini",
        task_type: taskType,
        key_name: kn,
        extra_params: extraParams,
      } as any);
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  // ── Fetch models ─────────────────────────────────────────────────────────
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
      {!isChatGPTWeb && (
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
      )}

      {/* ── ChatGPT Web: OAuth flow ──────────────────────────────────────── */}
      {isChatGPTWeb && (
        <div style={{
          background: "var(--color-tag)", borderRadius: 8,
          padding: "14px 16px", marginBottom: 12,
        }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
            <select
              className="admin-input"
              style={{ flex: 1 }}
              value={form.provider_type}
              onChange={e => {
                const pt = e.target.value;
                setForm(f => ({ ...f, provider_type: pt, model: "", name: "", api_key: "" }));
                setOAuthStep("idle");
                setOAuthDeviceCode(null);
              }}
            >
              {PROVIDER_TYPES.map(pt => (
                <option key={pt.value} value={pt.value}>{pt.label}</option>
              ))}
            </select>
          </div>

          {oauthStep === "idle" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--color-ink-muted)", margin: "0 0 10px 0", lineHeight: 1.5 }}>
                Sign in with your ChatGPT account via browser OAuth.{" "}
                <strong style={{ color: "var(--color-accent)" }}>Your subscription models</strong>{" "}
                will be available at no extra cost. Tokens auto-refresh — no manual re-entry needed.
              </p>
              <Button variant="primary" size="sm" onClick={handleStartOAuth}>
                🔗 Connect ChatGPT
              </Button>
            </div>
          )}

          {oauthStep === "waiting" && oauthDeviceCode && (
            <div style={{
              background: "var(--color-surface)", borderRadius: 6,
              padding: "12px 14px", textAlign: "center",
            }}>
              <p style={{ fontSize: 13, margin: "0 0 6px 0", color: "var(--color-ink-muted)" }}>
                Open this URL in your browser:
              </p>
              <a
                href={oauthDeviceCode.verification_uri}
                target="_blank" rel="noopener"
                style={{
                  fontSize: 14, fontWeight: 600,
                  color: "var(--color-accent)",
                  wordBreak: "break-all",
                }}
              >
                {oauthDeviceCode.verification_uri}
              </a>
              <p style={{ fontSize: 13, margin: "8px 0 4px 0", color: "var(--color-ink-muted)" }}>
                And enter this code:
              </p>
              <code style={{
                fontSize: 22, fontWeight: 700,
                letterSpacing: 4, color: "var(--color-accent)",
                background: "var(--color-tag)", padding: "6px 16px",
                borderRadius: 6, display: "inline-block",
              }}>
                {oauthDeviceCode.user_code}
              </code>
              <p style={{ fontSize: 12, color: "var(--color-ink-muted)", marginTop: 8 }}>
                {oauthMessage}
              </p>
            </div>
          )}

          {oauthStep === "authorized" && (
            <div style={{
              background: "rgba(52, 211, 153, 0.1)", borderRadius: 6,
              padding: "10px 14px", marginBottom: 8,
              border: "1px solid rgba(52, 211, 153, 0.3)",
            }}>
              <span style={{ color: "#34d399", fontSize: 13 }}>✅ Connected to ChatGPT</span>
              <span style={{ fontSize: 12, color: "var(--color-ink-muted)", marginLeft: 8 }}>
                {oauthMessage}
              </span>
            </div>
          )}

          {oauthStep === "error" && (
            <div style={{
              background: "rgba(248, 113, 113, 0.1)", borderRadius: 6,
              padding: "10px 14px", marginBottom: 8,
              border: "1px solid rgba(248, 113, 113, 0.3)",
            }}>
              <span style={{ color: "#f87171", fontSize: 13 }}>❌ {oauthMessage}</span>
              <Button variant="ghost" size="sm" onClick={() => { setOAuthStep("idle"); setOAuthMessage(""); }}>
                Try again
              </Button>
            </div>
          )}
        </div>
      )}

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
      {!isChatGPTWeb || oauthStep === "authorized" ? (
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
      ) : null}

      {/* Provider name (auto-filled, editable) */}
      <input
        className="admin-input"
        placeholder={ai.providerName}
        value={form.name}
        onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
      />

      <div style={{ display: "flex", gap: 8 }}>
        <Button
          variant="primary"
          size="sm"
          loading={saving}
          disabled={isChatGPTWeb ? oauthStep !== "authorized" : !form.api_key}
          onClick={isChatGPTWeb && oauthStep === "authorized" ? handleSaveOAuth : handleSave}
        >
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
