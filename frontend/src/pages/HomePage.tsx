import { useState, useEffect, useCallback, useRef } from "react";
import { LayoutList, LayoutGrid, RefreshCw, Plus, ChevronDown } from "lucide-react";
import { SearchBar } from "../components/search/SearchBar";
import { DocumentCard } from "../components/documents/DocumentCard";
import { DocumentViewer } from "../components/documents/DocumentViewer";
import { UploadZone } from "../components/documents/UploadZone";
import { KeyboardHelp } from "../components/ui/KeyboardHelp";
import { Button } from "../components/ui/Button";
import { useT } from "../i18n";
import { useKeyboard } from "../hooks/useKeyboard";
import { searchDocuments, syncLibrary } from "../api/documents";
import type { SearchMode, ViewMode, GridSize, SearchResult } from "../types";
import "./HomePage.css";

const GRID_SIZES: GridSize[] = ["sm", "md", "lg", "xl"];

export function HomePage() {
  const { t } = useT();

  // Search state
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("fulltext");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // View state
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [gridSize, setGridSize] = useState<GridSize>("md");

  // Viewer
  const [viewerIdx, setViewerIdx] = useState<number | null>(null);

  // Upload drawer
  const [showUpload, setShowUpload] = useState(false);

  // Sync
  const [syncing, setSyncing] = useState(false);

  // Keyboard help
  const [showHelp, setShowHelp] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const doSearch = useCallback(async () => {
    setLoading(true);
    try {
      const res = await searchDocuments({ query, mode, page_size: 48 });
      setResults(res.items);
      setTotal(res.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [query, mode]);

  useEffect(() => {
    const id = setTimeout(doSearch, query ? 350 : 0);
    return () => clearTimeout(id);
  }, [doSearch, query]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await syncLibrary();
      await doSearch();
    } finally {
      setSyncing(false);
    }
  };

  const cycleGridSize = () => {
    const idx = GRID_SIZES.indexOf(gridSize);
    setGridSize(GRID_SIZES[(idx + 1) % GRID_SIZES.length]);
  };

  const viewerDoc = viewerIdx !== null ? results[viewerIdx]?.document ?? null : null;

  // Keyboard shortcuts
  useKeyboard({
    "/":          () => { document.querySelector<HTMLInputElement>(".search-input")?.focus(); },
    "Escape":     () => { if (viewerIdx !== null) setViewerIdx(null); else setQuery(""); },
    "ArrowLeft":  () => { if (viewerIdx !== null && viewerIdx > 0) setViewerIdx(viewerIdx - 1); },
    "ArrowRight": () => { if (viewerIdx !== null && viewerIdx < results.length - 1) setViewerIdx(viewerIdx + 1); },
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
            onChange={setQuery}
            onModeChange={setMode}
            onSubmit={doSearch}
          />
        </section>

        {/* Toolbar */}
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

        {/* Upload zone (collapsible) */}
        {showUpload && (
          <div className="home-upload">
            <UploadZone onUploaded={() => { doSearch(); setTimeout(() => setShowUpload(false), 2000); }} />
          </div>
        )}

        {/* Content */}
        {loading ? (
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
        )}
      </div>

      {/* Document viewer */}
      <DocumentViewer
        doc={viewerDoc}
        onClose={() => setViewerIdx(null)}
        onPrev={() => setViewerIdx((i) => (i !== null ? i - 1 : null))}
        onNext={() => setViewerIdx((i) => (i !== null ? i + 1 : null))}
        hasPrev={viewerIdx !== null && viewerIdx > 0}
        hasNext={viewerIdx !== null && viewerIdx < results.length - 1}
      />

      {/* Keyboard shortcuts help */}
      <KeyboardHelp open={showHelp} onClose={() => setShowHelp(false)} />
    </main>
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
