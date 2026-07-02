import { useState } from "react";
import { Plus } from "lucide-react";
import { useT } from "../../i18n";
import { fetchTags } from "../../api/documents";

interface Props {
  existingTags: string[];
  onAdd: (tag: string) => void;
}

// ── Inline tag add — offers existing tags first to keep the taxonomy consistent ──

export function TagInput({ existingTags, onAdd }: Props) {
  const { t } = useT();
  const tp = t.tagPicker;

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [allTags, setAllTags] = useState<string[] | null>(null);
  const [value, setValue] = useState("");

  const handleOpen = async () => {
    setOpen(true);
    setValue("");
    if (allTags === null) {
      setLoading(true);
      try {
        setAllTags(await fetchTags());
      } catch {
        setAllTags([]);
      } finally {
        setLoading(false);
      }
    }
  };

  const handleAdd = (tag: string) => {
    const trimmed = tag.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    setOpen(false);
  };

  if (!open) {
    return (
      <button className="tag-add-btn" onClick={handleOpen} title={tp.title}>
        <Plus size={11} /> {tp.add}
      </button>
    );
  }

  const suggestions = (allTags ?? []).filter(
    (tag) =>
      !existingTags.includes(tag) &&
      (!value.trim() || tag.toLowerCase().includes(value.trim().toLowerCase()))
  );

  return (
    <div className="type-picker">
      <input
        className="admin-input"
        placeholder={tp.placeholder}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") handleAdd(value);
          else if (e.key === "Escape") setOpen(false);
        }}
        autoFocus
      />

      {loading ? (
        <p className="type-picker-loading">{tp.loading}</p>
      ) : suggestions.length > 0 ? (
        <div className="type-picker-suggestions">
          {suggestions.slice(0, 20).map((tag) => (
            <button key={tag} className="type-picker-option" onClick={() => handleAdd(tag)}>
              <span className="type-picker-option-name">{tag}</span>
            </button>
          ))}
        </div>
      ) : allTags && allTags.length === 0 ? (
        <p className="type-picker-loading">{tp.noTags}</p>
      ) : null}

      <div className="type-picker-actions">
        <button
          className="btn btn-primary btn-sm"
          disabled={!value.trim()}
          onClick={() => handleAdd(value)}
        >
          {t.add}
        </button>
        <button className="type-picker-cancel" onClick={() => setOpen(false)}>
          {tp.cancel}
        </button>
      </div>
    </div>
  );
}
