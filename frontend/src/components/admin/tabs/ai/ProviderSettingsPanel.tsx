import { useT } from "../../../../i18n";

// ── Provider settings panel ───────────────────────────────────────────────────

export function ProviderSettingsPanel({
  providerType,
  inferredCapabilities,
  settings,
  onChange,
}: {
  providerType: string;
  inferredCapabilities: Record<string, boolean>;
  settings: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}) {
  const { t } = useT();
  const ai = t.admin.ai;

  const overrides = (settings.capabilities ?? {}) as Record<string, boolean>;
  const capabilityEditor = (
    <div style={{ borderTop: "1px solid var(--color-border)", paddingTop: 10 }}>
      <p style={{ fontSize: 12, fontWeight: 600, marginBottom: 4 }}>{ai.capabilitiesLabel}</p>
      <p className="text-xs text-muted" style={{ marginBottom: 8 }}>{ai.capabilitiesHint}</p>
      {(["text", "vision", "ocr", "analysis", "batch"] as const).map(key => {
        const checked = overrides[key] ?? inferredCapabilities[key] ?? false;
        return (
          <label key={key} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, marginBottom: 6 }}>
            <input
              type="checkbox"
              checked={checked}
              onChange={e => onChange("capabilities", { ...overrides, [key]: e.target.checked })}
            />
            {ai.capabilityNames[key]}
          </label>
        );
      })}
    </div>
  );

  if (providerType === "mistral") {
    const policy = (settings.image_policy ?? "placeholder") as string;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <p className="text-xs text-muted" style={{ marginBottom: 8 }}>{ai.imagePolicyHint}</p>
          {[
            { value: "placeholder", label: ai.imagePolicyPlaceholder },
            { value: "strip",       label: ai.imagePolicyStrip },
          ].map(opt => (
            <label key={opt.value} style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, marginBottom: 6 }}>
              <input
                type="radio"
                name="image_policy"
                value={opt.value}
                checked={policy === opt.value}
                onChange={() => onChange("image_policy", opt.value)}
              />
              {opt.label}
            </label>
          ))}
        </div>
        {capabilityEditor}
      </div>
    );
  }

  // Chat providers: temperature + max_tokens
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <label style={{ fontSize: 12, color: "var(--color-ink-muted)", display: "block", marginBottom: 2 }}>
          {ai.temperatureLabel}
        </label>
        <p className="text-xs text-muted" style={{ marginBottom: 4 }}>{ai.temperatureHint}</p>
        <input
          className="admin-input"
          type="number"
          min="0" max="2" step="0.1"
          value={settings.temperature != null ? String(settings.temperature) : ""}
          placeholder="1.0"
          onChange={e => onChange("temperature", e.target.value === "" ? undefined : parseFloat(e.target.value))}
        />
      </div>
      <div>
        <label style={{ fontSize: 12, color: "var(--color-ink-muted)", display: "block", marginBottom: 2 }}>
          {ai.maxTokensLabel}
        </label>
        <p className="text-xs text-muted" style={{ marginBottom: 4 }}>{ai.maxTokensHint}</p>
        <input
          className="admin-input"
          type="number"
          min="256" max="32768" step="256"
          value={settings.max_tokens != null ? String(settings.max_tokens) : ""}
          placeholder="2048"
          onChange={e => onChange("max_tokens", e.target.value === "" ? undefined : parseInt(e.target.value))}
        />
      </div>
      {capabilityEditor}
    </div>
  );
}
