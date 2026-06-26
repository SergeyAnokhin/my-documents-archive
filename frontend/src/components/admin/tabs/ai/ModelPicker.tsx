import { useState, useMemo } from "react";
import { useT } from "../../../../i18n";
import type { ProviderModel, ArenaRating } from "../../../../types";
import { lookupModelRating, inputPrice, blendedPrice, fmtCtx } from "./aiUtils";
import { RatingStars } from "./RatingStars";

// ── Model picker with search and sort ────────────────────────────────────────

type SortKey = "default" | "rating" | "price";

export function ModelPicker({
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

  // Numeric sort key for rating: prefer actual Elo, approximate from stars as fallback
  const ratingKey = (m: ProviderModel) => {
    const r = lookupModelRating(ratings, m.id, forVision);
    return r.elo ?? (r.stars * 70 + 1050);
  };

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim();
    const base = forVision ? models.filter(m => m.supports_vision) : models;
    let result = q ? base.filter(m => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)) : base;
    if (sortBy === "rating") {
      result = [...result].sort((a, b) => ratingKey(b) - ratingKey(a));
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
            const rating = lookupModelRating(ratings, m.id, forVision);
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
                <RatingStars rating={rating} forVision={forVision} />
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
