import { useState } from "react";
import { Lock, Pencil } from "lucide-react";
import type { TypeSuggestion } from "../../types";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";
import type { Lang } from "../../i18n";
import { patchDocumentType, suggestDocumentTypes } from "../../api/documents";
import { labelForType } from "./typeIcons";

export function formatTypeName(type: string, lang: Lang = "en") {
  return labelForType(type, lang);
}

// ── Inline type picker ──────────────────────────────────────────────────────

interface TypePickerProps {
  docId: number;
  currentType?: string;
  isManual?: boolean;
  onSaved: (newType: string) => void;
}

export function TypePicker({ docId, currentType, isManual, onSaved }: TypePickerProps) {
  const { t, lang } = useT();
  const tp = t.typePicker;
  const isUnclassified = !currentType || currentType === "unclassified" || currentType === "other";

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<TypeSuggestion[] | null>(null);
  const [custom, setCustom] = useState("");
  const [saving, setSaving] = useState(false);

  const handleOpen = async () => {
    setOpen(true);
    setCustom("");
    if (suggestions === null) {
      setLoading(true);
      try {
        const res = await suggestDocumentTypes(docId);
        setSuggestions(res.suggestions);
      } catch {
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    }
  };

  const handleSelect = async (type: string) => {
    if (!type.trim()) return;
    setSaving(true);
    try {
      await patchDocumentType(docId, type.trim());
      onSaved(type.trim());
      setOpen(false);
    } catch {
      // keep open so user can retry
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button
        className={`type-badge-btn${isUnclassified ? " unclassified" : ""}`}
        onClick={handleOpen}
        title={tp.title}
      >
        {isUnclassified
          ? tp.unclassified
          : formatTypeName(currentType!, lang)}
        {isManual && !isUnclassified && (
          <Lock size={10} className="type-badge-lock" />
        )}
        <Pencil size={10} className="type-badge-edit" />
      </button>
    );
  }

  return (
    <div className="type-picker">
      {loading ? (
        <p className="type-picker-loading">{tp.loading}</p>
      ) : suggestions && suggestions.length > 0 ? (
        <>
          <p className="type-picker-label">{tp.suggested}</p>
          <div className="type-picker-suggestions">
            {suggestions.map((s) => (
              <button
                key={s.type}
                className="type-picker-option"
                onClick={() => handleSelect(s.type)}
                disabled={saving}
                title={s.reason}
              >
                <span className="type-picker-option-name">{formatTypeName(s.type, lang)}</span>
                <span className="type-picker-option-conf">{Math.round(s.confidence * 100)}%</span>
              </button>
            ))}
          </div>
        </>
      ) : (
        <p className="type-picker-loading">{tp.noSuggestions}</p>
      )}

      <div className="type-picker-custom">
        <input
          className="admin-input"
          placeholder={tp.customPlaceholder}
          value={custom}
          onChange={e => setCustom(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") handleSelect(custom); }}
          autoFocus={!loading}
        />
      </div>

      <div className="type-picker-actions">
        <Button
          size="sm"
          variant="primary"
          loading={saving}
          onClick={() => handleSelect(custom)}
          disabled={!custom.trim()}
        >
          {tp.save}
        </Button>
        <button className="type-picker-cancel" onClick={() => setOpen(false)}>
          {tp.cancel}
        </button>
      </div>
    </div>
  );
}
