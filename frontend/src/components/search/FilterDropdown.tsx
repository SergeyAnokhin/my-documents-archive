import { useRef, useEffect, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import "./FilterDropdown.css";

export interface DropdownOption {
  value: string;
  label: string;
  count?: number;
}

interface Props {
  /** Label shown when nothing is selected */
  label: string;
  /** "All years" / "All languages" — the clear option */
  clearLabel: string;
  options: DropdownOption[];
  value: string | null;
  onSelect: (v: string | null) => void;
}

export function FilterDropdown({ label, clearLabel, options, value, onSelect }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const selected = options.find((o) => o.value === value) ?? null;

  // Close when clicking outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const pick = (v: string | null) => {
    onSelect(v);
    setOpen(false);
  };

  return (
    <div className="fdd" ref={wrapRef}>
      <button
        type="button"
        className={`fdd-btn${value ? " fdd-btn--active" : ""}${open ? " fdd-btn--open" : ""}`}
        onClick={() => setOpen((s) => !s)}
      >
        <span className="fdd-btn-label">{selected ? selected.label : label}</span>
        <ChevronDown size={12} className="fdd-chevron" />
      </button>

      {open && (
        <div className="fdd-menu">
          {/* Clear option */}
          <button
            type="button"
            className={`fdd-item fdd-item--clear${!value ? " fdd-item--selected" : ""}`}
            onClick={() => pick(null)}
          >
            <span>{clearLabel}</span>
            {!value && <Check size={12} />}
          </button>
          <div className="fdd-divider" />
          {/* Scrollable list */}
          <div className="fdd-scroll">
            {options.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className={`fdd-item${value === opt.value ? " fdd-item--selected" : ""}`}
                onClick={() => pick(opt.value)}
              >
                <span className="fdd-item-label">{opt.label}</span>
                <span className="fdd-item-right">
                  {opt.count !== undefined && (
                    <span className={`fdd-count${opt.count > 0 ? " fdd-count--nonzero" : ""}`}>
                      {opt.count}
                    </span>
                  )}
                  {value === opt.value && <Check size={12} />}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
