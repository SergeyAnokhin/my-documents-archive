import { useRef, type ChangeEvent, type FormEvent } from "react";
import { Search, X } from "lucide-react";
import type { SearchMode } from "../../types";
import { useT } from "../../i18n";
import "./SearchBar.css";

interface Props {
  value: string;
  mode: SearchMode;
  onChange: (v: string) => void;
  onModeChange: (m: SearchMode) => void;
  onSubmit: () => void;
}

export function SearchBar({ value, mode, onChange, onModeChange, onSubmit }: Props) {
  const { t } = useT();
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <form className="search-bar" onSubmit={handleSubmit} role="search">
      <div className="search-input-wrap">
        <Search size={18} className="search-icon" aria-hidden="true" />
        <input
          ref={inputRef}
          type="search"
          className="search-input"
          placeholder={t.searchPlaceholder}
          value={value}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
          aria-label={t.searchPlaceholder}
          autoComplete="off"
        />
        {value && (
          <button
            type="button"
            className="search-clear"
            onClick={() => { onChange(""); inputRef.current?.focus(); }}
            aria-label="Clear search"
          >
            <X size={15} />
          </button>
        )}
      </div>

      {/* Mode pills */}
      <div className="search-modes" role="radiogroup" aria-label="Search mode">
        {(["fulltext", "semantic", "hybrid"] as SearchMode[]).map((m) => (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={mode === m}
            className={`search-mode-pill${mode === m ? " active" : ""}`}
            onClick={() => onModeChange(m)}
          >
            {t.searchMode[m]}
          </button>
        ))}
      </div>
    </form>
  );
}
