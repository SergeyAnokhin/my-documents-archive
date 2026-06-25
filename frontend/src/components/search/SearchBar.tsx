import { useRef, useState, useEffect, type ChangeEvent, type FormEvent } from "react";
import { Search, X, Mic, MicOff } from "lucide-react";
import type { SearchMode } from "../../types";
import { useT } from "../../i18n";
import { FilterDropdown, type DropdownOption } from "./FilterDropdown";
import "./SearchBar.css";

const LANG_BCP47: Record<string, string> = { en: "en-US", ru: "ru-RU", fr: "fr-FR" };

const LANG_OPTIONS: DropdownOption[] = [
  { value: "ru", label: "Русский" },
  { value: "fr", label: "Français" },
  { value: "en", label: "English" },
];

function buildYearOptions(): DropdownOption[] {
  const current = new Date().getFullYear();
  return Array.from({ length: current - 1999 }, (_, i) => {
    const y = String(current - i);
    return { value: y, label: y };
  });
}

const YEAR_OPTIONS = buildYearOptions();

interface Props {
  value: string;
  mode: SearchMode;
  onChange: (v: string) => void;
  onModeChange: (m: SearchMode) => void;
  onSubmit: () => void;
  filterLang: string | null;
  onFilterLang: (lang: string | null) => void;
  filterYear: string | null;
  onFilterYear: (year: string | null) => void;
}

export function SearchBar({
  value, mode, onChange, onModeChange, onSubmit,
  filterLang, onFilterLang, filterYear, onFilterYear,
}: Props) {
  const { t, lang } = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recogRef = useRef<any>(null);
  const [listening, setListening] = useState(false);

  const hasSpeech =
    typeof window !== "undefined" &&
    ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  const toggleVoice = () => {
    if (!hasSpeech) return;
    if (listening) { recogRef.current?.stop(); return; }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const r: any = new SR();
    r.lang = LANG_BCP47[lang] ?? "en-US";
    r.interimResults = false;
    r.maxAlternatives = 1;
    r.onstart = () => setListening(true);
    r.onend   = () => setListening(false);
    r.onerror = () => setListening(false);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    r.onresult = (e: any) => {
      const text = e.results[0][0].transcript;
      onChange(text);
      setTimeout(() => onSubmit(), 50);
    };
    recogRef.current = r;
    r.start();
  };

  useEffect(() => () => { recogRef.current?.stop(); }, []);

  const isAsk = mode === "ask";
  const placeholder = listening
    ? t.voiceListening
    : isAsk
      ? t.aiSearch.placeholder
      : t.searchPlaceholder;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit();
  };

  return (
    <form className="search-bar" onSubmit={handleSubmit} role="search">
      {/* Input row */}
      <div className={`search-input-wrap${listening ? " search-input-wrap--listening" : ""}`}>
        <Search size={18} className="search-icon" aria-hidden="true" />
        <input
          ref={inputRef}
          type="search"
          className={`search-input${hasSpeech ? " search-input--has-mic" : ""}`}
          placeholder={placeholder}
          value={value}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
          aria-label={placeholder}
          autoComplete="off"
        />
        <div className="search-right-btns">
          {value && (
            <button
              type="button"
              className="search-clear"
              onClick={() => { onChange(""); inputRef.current?.focus(); }}
              aria-label="Clear"
            >
              <X size={15} />
            </button>
          )}
          {hasSpeech && (
            <button
              type="button"
              className={`search-mic${listening ? " search-mic--active" : ""}`}
              onClick={toggleVoice}
              title={listening ? t.voiceListening : t.voiceSearch}
              aria-label={listening ? t.voiceListening : t.voiceSearch}
            >
              {listening ? <MicOff size={16} /> : <Mic size={16} />}
            </button>
          )}
        </div>
      </div>

      {/* Bottom row: mode pills + filter dropdowns */}
      <div className="search-bottom-row">
        {/* Mode pills */}
        <div className="search-modes" role="radiogroup" aria-label="Search mode">
          {(["search", "ask"] as SearchMode[]).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              className={`search-mode-pill${mode === m ? " active" : ""}${m === "ask" ? " search-mode-pill--ai" : ""}`}
              onClick={() => onModeChange(m)}
            >
              {t.searchMode[m]}
            </button>
          ))}
        </div>

        {/* Filter dropdowns — always shown */}
        <div className="search-filters">
          <FilterDropdown
            label={t.filters.year}
            clearLabel={t.filters.allYears}
            options={YEAR_OPTIONS}
            value={filterYear}
            onSelect={onFilterYear}
          />
          <FilterDropdown
            label={t.filters.language}
            clearLabel={t.filters.allLanguages}
            options={LANG_OPTIONS}
            value={filterLang}
            onSelect={onFilterLang}
          />
          <button type="submit" className="search-submit-btn">
            {isAsk ? t.aiSearch.submit : t.searchMode.search}
          </button>
        </div>
      </div>
    </form>
  );
}
