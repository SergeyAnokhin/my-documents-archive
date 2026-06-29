import { useRef, useState, useEffect, type ChangeEvent, type FormEvent } from "react";
import { Search, X, Mic, MicOff, History, Clock } from "lucide-react";
import type { SearchMode } from "../../types";
import { useT } from "../../i18n";
import { FilterDropdown, type DropdownOption } from "./FilterDropdown";
import { useSearchHistory } from "../../hooks/useSearchHistory";
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
  depth: number;
  onDepthChange: (d: number) => void;
  devMode: boolean;
  onDevModeChange: (v: boolean) => void;
}

export function SearchBar({
  value, mode, onChange, onModeChange, onSubmit,
  filterLang, onFilterLang, filterYear, onFilterYear,
  depth, onDepthChange, devMode, onDevModeChange,
}: Props) {
  const { t, lang } = useT();
  const inputRef = useRef<HTMLInputElement>(null);
  const historyRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recogRef = useRef<any>(null);
  const [listening, setListening] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const histSearch = useSearchHistory("search");
  const histAsk = useSearchHistory("ask");
  const hist = mode === "ask" ? histAsk : histSearch;

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

  // Close history dropdown on outside click
  useEffect(() => {
    if (!showHistory) return;
    const handler = (e: MouseEvent) => {
      if (historyRef.current && !historyRef.current.contains(e.target as Node)) {
        setShowHistory(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showHistory]);

  const isAsk = mode === "ask";
  const placeholder = listening
    ? t.voiceListening
    : isAsk
      ? t.aiSearch.placeholder
      : t.searchPlaceholder;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim()) hist.save(value.trim());
    setShowHistory(false);
    onSubmit();
  };

  return (
    <form className="search-bar" onSubmit={handleSubmit} role="search">
      {/* Input row + history dropdown wrapper */}
      <div className="search-input-outer" ref={historyRef}>
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
            {hist.items.length > 0 && (
              <button
                type="button"
                className={`search-history-btn${showHistory ? " active" : ""}`}
                onClick={() => setShowHistory(v => !v)}
                title={t.searchHistory.title}
                aria-label={t.searchHistory.title}
              >
                <History size={15} />
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

        {/* History dropdown */}
        {showHistory && hist.items.length > 0 && (
          <div className="search-history-dropdown">
            <div className="search-history-header text-xs text-muted">{t.searchHistory.title}</div>
            {hist.items.map((item, i) => (
              <button
                key={i}
                type="button"
                className="search-history-item"
                onClick={() => { onChange(item); setShowHistory(false); }}
              >
                <Clock size={12} className="search-history-item-icon" />
                <span className="search-history-item-text">{item}</span>
              </button>
            ))}
            <div className="search-history-footer">
              <button type="button" className="search-history-clear" onClick={hist.clear}>
                {t.searchHistory.clear}
              </button>
              <label className="search-history-max-label">
                {t.searchHistory.maxLabel}
                <input
                  type="number"
                  className="search-history-max-input"
                  min={1}
                  max={50}
                  value={hist.max}
                  onChange={e => hist.setMax(Number(e.target.value))}
                />
                {t.searchHistory.maxSuffix}
              </label>
            </div>
          </div>
        )}
      </div>

      {/* Bottom row: mode pills + depth (AI only) + filter dropdowns */}
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

        {/* Depth pills — AI mode only */}
        {isAsk && (
          <div className="search-depth" role="group" aria-label="Search depth">
            {([1, 2, 3] as const).map((d) => {
              const label = [t.aiSearch.depthFast, t.aiSearch.depthNormal, t.aiSearch.depthDeep][d - 1];
              return (
                <button
                  key={d}
                  type="button"
                  className={`search-depth-pill${depth === d ? " active" : ""}`}
                  onClick={() => onDepthChange(d)}
                  title={label}
                >
                  {label}
                </button>
              );
            })}
          </div>
        )}

        {/* Filter dropdowns + submit */}
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
          {isAsk && (
            <button
              type="button"
              className={`search-devmode-btn${devMode ? " active" : ""}`}
              onClick={() => onDevModeChange(!devMode)}
              title={t.aiSearch.devMode}
              aria-label={t.aiSearch.devMode}
            >
              ⚙
            </button>
          )}
          <button type="submit" className="search-submit-btn">
            {isAsk ? t.aiSearch.submit : t.searchMode.search}
          </button>
        </div>
      </div>
    </form>
  );
}
