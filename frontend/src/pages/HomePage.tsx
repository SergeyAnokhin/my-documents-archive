import { useState, useEffect, useCallback, useRef } from "react";
import { LayoutList, LayoutGrid, RefreshCw, Plus, ChevronDown, Check, Loader2 } from "lucide-react";
import { SearchBar } from "../components/search/SearchBar";
import { AIAnswer } from "../components/search/AIAnswer";
import { DocumentCard } from "../components/documents/DocumentCard";
import { DocumentViewer } from "../components/documents/DocumentViewer";
import { UploadZone } from "../components/documents/UploadZone";
import { KeyboardHelp } from "../components/ui/KeyboardHelp";
import { Button } from "../components/ui/Button";
import { useT } from "../i18n";
import { useKeyboard } from "../hooks/useKeyboard";
import { searchDocuments, syncLibrary, askDocuments } from "../api/documents";
import type { SearchMode, ViewMode, GridSize, SearchResult, AIAnswerResponse } from "../types";
import "./HomePage.css";

const GRID_SIZES: GridSize[] = ["sm", "md", "lg", "xl"];

export function HomePage() {
  const { t, lang } = useT();

  // Search state
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("search");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // Filter state (year is a string to match option values)
  const [filterLang, setFilterLang] = useState<string | null>(null);
  const [filterYear, setFilterYear] = useState<string | null>(null);

  // AI ask state
  const [aiAnswer, setAiAnswer] = useState<AIAnswerResponse | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiViewerIdx, setAiViewerIdx] = useState<number | null>(null);
  const [depth, setDepth] = useState(2);
  const [devMode, setDevMode] = useState(false);

  // View state
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [gridSize, setGridSize] = useState<GridSize>("md");

  // Viewer (regular search results)
  const [viewerIdx, setViewerIdx] = useState<number | null>(null);

  // Upload drawer
  const [showUpload, setShowUpload] = useState(false);

  // Sync
  const [syncing, setSyncing] = useState(false);

  // Keyboard help
  const [showHelp, setShowHelp] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // ── Regular search ──────────────────────────────────────────────────────────

  const doSearch = useCallback(async () => {
    if (mode === "ask") return;
    setLoading(true);
    try {
      const res = await searchDocuments({
        query,
        mode: "hybrid",   // always use hybrid (best of fulltext + semantic)
        page_size: 48,
        ...(filterYear ? { year: filterYear } : {}),
        ...(filterLang ? { language: filterLang } : {}),
      });
      setResults(res.items);
      setTotal(res.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [query, mode, filterYear, filterLang]);

  useEffect(() => {
    const id = setTimeout(doSearch, query ? 350 : 0);
    return () => clearTimeout(id);
  }, [doSearch, query]);

  // Re-fetch when sync happens from AdminPanel or any other source
  useEffect(() => {
    const handler = () => { if (mode !== "ask") doSearch(); };
    window.addEventListener("docintell:library-changed", handler);
    return () => window.removeEventListener("docintell:library-changed", handler);
  }, [doSearch, mode]);

  // Also re-search immediately when filters change (no debounce needed)
  useEffect(() => {
    if (mode !== "ask") doSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterYear, filterLang]);

  // ── AI ask ──────────────────────────────────────────────────────────────────

  const doAsk = useCallback(async () => {
    if (!query.trim()) return;
    setAiLoading(true);
    setAiAnswer(null);
    try {
      const res = await askDocuments(query, lang, filterYear, filterLang, depth);
      setAiAnswer(res);
    } catch {
      /* ignore */
    } finally {
      setAiLoading(false);
    }
  }, [query, lang, filterYear, filterLang, depth]);

  // ── Mode change ─────────────────────────────────────────────────────────────

  const handleModeChange = (m: SearchMode) => {
    setMode(m);
    if (m === "ask") {
      setResults([]);
      setTotal(0);
    } else {
      setAiAnswer(null);
      setAiViewerIdx(null);
    }
  };

  // Clear previous AI answer when user edits the query
  const handleQueryChange = (v: string) => {
    setQuery(v);
    if (mode === "ask") setAiAnswer(null);
  };

  // ── Submit (Enter / voice) ──────────────────────────────────────────────────

  const handleSubmit = () => {
    if (mode === "ask") doAsk();
    else doSearch();
  };

  // ── Sync ────────────────────────────────────────────────────────────────────

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncLibrary();
      window.dispatchEvent(new CustomEvent("docintell:library-changed"));
    } finally {
      setSyncing(false);
    }
  };

  // ── Viewer helpers ──────────────────────────────────────────────────────────

  const cycleGridSize = () => {
    const idx = GRID_SIZES.indexOf(gridSize);
    setGridSize(GRID_SIZES[(idx + 1) % GRID_SIZES.length]);
  };

  // Regular results viewer
  const viewerDoc = viewerIdx !== null ? results[viewerIdx]?.document ?? null : null;

  // AI sources viewer
  const aiViewerDoc = aiViewerIdx !== null ? (aiAnswer?.sources[aiViewerIdx] ?? null) : null;

  // Keyboard shortcuts
  useKeyboard({
    "/":          () => { document.querySelector<HTMLInputElement>(".search-input")?.focus(); },
    "Escape":     () => {
      if (aiViewerIdx !== null) { setAiViewerIdx(null); return; }
      if (viewerIdx !== null)   { setViewerIdx(null);   return; }
      setQuery("");
    },
    "ArrowLeft":  () => {
      if (aiViewerIdx !== null && aiViewerIdx > 0) setAiViewerIdx(aiViewerIdx - 1);
      else if (viewerIdx !== null && viewerIdx > 0) setViewerIdx(viewerIdx - 1);
    },
    "ArrowRight": () => {
      if (aiViewerIdx !== null && aiAnswer && aiViewerIdx < aiAnswer.sources.length - 1) setAiViewerIdx(aiViewerIdx + 1);
      else if (viewerIdx !== null && viewerIdx < results.length - 1) setViewerIdx(viewerIdx + 1);
    },
    "1":          () => setViewMode("list"),
    "2":          () => setViewMode("grid"),
    "+":          () => cycleGridSize(),
    "-":          () => { const idx = GRID_SIZES.indexOf(gridSize); setGridSize(GRID_SIZES[Math.max(0, idx - 1)]); },
    "?":          () => setShowHelp(true),
  });

  return (
    <main className="home-page">
      <div className="container">

        {/* Hero search area */}
        <section className="home-hero">
          <h1 className="home-tagline">{t.appTagline}</h1>
          <SearchBar
            value={query}
            mode={mode}
            onChange={handleQueryChange}
            onModeChange={handleModeChange}
            onSubmit={handleSubmit}
            filterLang={filterLang}
            onFilterLang={setFilterLang}
            filterYear={filterYear}
            onFilterYear={(y) => setFilterYear(y)}
            depth={depth}
            onDepthChange={setDepth}
            devMode={devMode}
            onDevModeChange={setDevMode}
          />
        </section>

        {/* Toolbar — hidden in ask mode */}
        {mode !== "ask" && (
          <div className="home-toolbar">
            <div className="toolbar-left">
              <span className="toolbar-count text-sm text-muted">
                {total > 0 ? `${total} documents` : ""}
              </span>
            </div>
            <div className="toolbar-right">
              <Button
                variant="ghost" size="sm"
                icon={<RefreshCw size={14} />}
                loading={syncing}
                onClick={handleSync}
              >
                {t.syncButton}
              </Button>
              <Button
                variant="secondary" size="sm"
                icon={<Plus size={14} />}
                onClick={() => setShowUpload((v) => !v)}
              >
                {t.uploadTitle}
              </Button>
              <div className="view-toggle">
                <button
                  className={`view-btn${viewMode === "list" ? " active" : ""}`}
                  onClick={() => setViewMode("list")}
                  title={t.viewList}
                >
                  <LayoutList size={16} />
                </button>
                <button
                  className={`view-btn${viewMode === "grid" ? " active" : ""}`}
                  onClick={() => setViewMode("grid")}
                  title={t.viewGrid}
                >
                  <LayoutGrid size={16} />
                </button>
                {viewMode === "grid" && (
                  <button className="view-btn" onClick={cycleGridSize} title="Change grid size">
                    <ChevronDown size={14} />
                    <span className="text-xs">{gridSize.toUpperCase()}</span>
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Upload zone (collapsible) */}
        {showUpload && mode !== "ask" && (
          <div className="home-upload">
            <UploadZone onUploaded={() => { doSearch(); setTimeout(() => setShowUpload(false), 2000); }} />
          </div>
        )}

        {/* ── AI mode content ── */}
        {mode === "ask" && (
          <div className="ai-mode-content">
            {aiLoading && <AISearchProgress t={t} />}
            {!aiLoading && aiAnswer && (
              <AIAnswer
                answer={aiAnswer.answer}
                sources={aiAnswer.sources}
                cost={aiAnswer.cost}
                noProvider={aiAnswer.no_provider}
                onDocClick={(i) => setAiViewerIdx(i)}
                tokensIn={aiAnswer.tokens_in}
                tokensOut={aiAnswer.tokens_out}
                modelName={aiAnswer.model_name}
                docsSent={aiAnswer.docs_sent}
                devMode={devMode}
              />
            )}
            {!aiLoading && !aiAnswer && (
              <AskHint t={t} />
            )}
          </div>
        )}

        {/* ── Regular search content ── */}
        {mode !== "ask" && (
          loading ? (
            <DocumentSkeleton viewMode={viewMode} gridSize={gridSize} />
          ) : results.length === 0 ? (
            <EmptyState query={query} onUpload={() => setShowUpload(true)} />
          ) : viewMode === "list" ? (
            <div className="doc-list">
              {results.map((r, i) => (
                <DocumentCard
                  key={r.document.id}
                  doc={r.document}
                  highlight={r.highlight}
                  mode="list"
                  onClick={() => setViewerIdx(i)}
                />
              ))}
            </div>
          ) : (
            <div className={`doc-grid doc-grid-size-${gridSize}`}>
              {results.map((r, i) => (
                <DocumentCard
                  key={r.document.id}
                  doc={r.document}
                  mode="grid"
                  gridSize={gridSize}
                  onClick={() => setViewerIdx(i)}
                />
              ))}
            </div>
          )
        )}
      </div>

      {/* Document viewer — regular results */}
      <DocumentViewer
        doc={viewerDoc}
        onClose={() => setViewerIdx(null)}
        onPrev={() => setViewerIdx((i) => (i !== null ? i - 1 : null))}
        onNext={() => setViewerIdx((i) => (i !== null ? i + 1 : null))}
        hasPrev={viewerIdx !== null && viewerIdx > 0}
        hasNext={viewerIdx !== null && viewerIdx < results.length - 1}
      />

      {/* Document viewer — AI sources */}
      <DocumentViewer
        doc={aiViewerDoc}
        onClose={() => setAiViewerIdx(null)}
        onPrev={() => setAiViewerIdx((i) => (i !== null ? i - 1 : null))}
        onNext={() => setAiViewerIdx((i) => (i !== null ? i + 1 : null))}
        hasPrev={aiViewerIdx !== null && aiViewerIdx > 0}
        hasNext={aiViewerIdx !== null && aiAnswer !== null && aiViewerIdx < aiAnswer.sources.length - 1}
      />

      {/* Keyboard shortcuts help */}
      <KeyboardHelp open={showHelp} onClose={() => setShowHelp(false)} />
    </main>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

const _STEP_DELAYS = [0, 320, 680, 1050]; // ms when each step becomes active

function AISearchProgress({ t }: { t: ReturnType<typeof useT>["t"] }) {
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    const timers = _STEP_DELAYS.slice(1).map((ms, i) =>
      window.setTimeout(() => setActiveIdx(i + 1), ms)
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  const steps = [
    t.aiSearch.stepText,
    t.aiSearch.stepSemantic,
    t.aiSearch.stepRank,
    t.aiSearch.stepLlm,
  ];

  return (
    <div className="ai-search-progress">
      {steps.map((label, i) => {
        const done   = i < activeIdx;
        const active = i === activeIdx;
        return (
          <div key={i} className={`ai-progress-step${done ? " done" : active ? " active" : ""}`}>
            <span className="ai-step-icon">
              {done   ? <Check size={13} />
               : active ? <Loader2 size={13} className="ai-step-spin" />
               : null}
            </span>
            <span>{label}</span>
          </div>
        );
      })}
    </div>
  );
}

function AskHint({ t }: { t: ReturnType<typeof useT>["t"] }) {
  return (
    <div className="ask-hint">
      <div className="ask-hint-icon">✨</div>
      <p className="ask-hint-text text-muted">{t.aiSearch.placeholder}</p>
    </div>
  );
}

function EmptyState({ query, onUpload }: { query: string; onUpload: () => void }) {
  const { t } = useT();
  return (
    <div className="empty-state">
      <div className="empty-state-icon">📂</div>
      <h2 className="empty-state-title">{query ? t.noResults : t.noDocuments}</h2>
      <p className="empty-state-hint text-muted">{query ? t.noResultsHint : t.noDocumentsHint}</p>
      {!query && (
        <Button variant="primary" onClick={onUpload} icon={<Plus size={16} />}>
          {t.uploadTitle}
        </Button>
      )}
    </div>
  );
}

function DocumentSkeleton({ viewMode, gridSize }: { viewMode: ViewMode; gridSize: GridSize }) {
  const count = 8;
  if (viewMode === "list") {
    return (
      <div className="doc-list">
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 80, borderRadius: 12 }} />
        ))}
      </div>
    );
  }
  return (
    <div className={`doc-grid doc-grid-size-${gridSize}`}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="skeleton" style={{ borderRadius: 12, aspectRatio: "3/4" }} />
      ))}
    </div>
  );
}
