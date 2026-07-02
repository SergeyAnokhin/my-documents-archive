import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { SearchBar } from "../components/search/SearchBar";
import { DocumentViewer } from "../components/documents/DocumentViewer";
import { UploadZone } from "../components/documents/UploadZone";
import { KeyboardHelp } from "../components/ui/KeyboardHelp";
import { useT } from "../i18n";
import { useKeyboard } from "../hooks/useKeyboard";
import { useAdvancedMode } from "../contexts/AdvancedModeContext";
import { searchDocuments, syncLibrary, askDocuments, fetchEmbeddedIds, fetchQualityCounts, getFolderTree, getDocument } from "../api/documents";
import type { SearchMode, ViewMode, LayoutMode, GridSize, SearchResult, AIAnswerResponse, Document, FolderTreeNode } from "../types";
import { HomePageToolbar } from "./home/HomePageToolbar";
import { HomePageAIMode } from "./home/HomePageAIMode";
import { HomePageResults } from "./home/HomePageResults";
import { HomePageFolderResults } from "./home/HomePageFolderResults";
import "./HomePage.css";

const GRID_SIZES: GridSize[] = ["sm", "md", "lg", "xl"];

export function HomePage() {
  const { t, lang } = useT();
  const { advancedMode } = useAdvancedMode();

  // Search state
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("search");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  // Filter state (year is a string to match option values)
  const [filterLang, setFilterLang] = useState<string | null>(null);
  const [filterYear, setFilterYear] = useState<string | null>(null);
  const [filterQuality, setFilterQuality] = useState<string | null>(null);
  const [filterDirectory, setFilterDirectory] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<string | null>(null);

  // Quality counts for the filter dropdown
  const [qualityCounts, setQualityCounts] = useState<Record<string, number>>({});

  // AI ask state
  const [aiAnswer, setAiAnswer] = useState<AIAnswerResponse | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiViewerIdx, setAiViewerIdx] = useState<number | null>(null);
  const [depth, setDepth] = useState(2);
  const [devMode, setDevMode] = useState(false);
  const [embeddedIds, setEmbeddedIds] = useState<Set<number>>(new Set());

  // View state
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [gridSize, setGridSize] = useState<GridSize>("md");
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("flat");

  // Folder browser (Explorer-style) state
  const [folderTree, setFolderTree] = useState<FolderTreeNode | null>(null);
  const [folderTreeLoading, setFolderTreeLoading] = useState(false);
  const [folderViewerIdx, setFolderViewerIdx] = useState<number | null>(null);
  const [folderViewerDoc, setFolderViewerDoc] = useState<Document | null>(null);

  // Viewer (regular search results)
  const [viewerIdx, setViewerIdx] = useState<number | null>(null);

  // Upload drawer
  const [showUpload, setShowUpload] = useState(false);

  // Thumbnail version overrides after image edits (client-side cache-bust)
  const [thumbVersions, setThumbVersions] = useState<Record<number, number>>({});

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
        ...(filterQuality ? { quality: filterQuality } : {}),
        ...(filterDirectory ? { folder: filterDirectory } : {}),
        ...(filterCategory ? { document_type: filterCategory } : {}),
      });
      setResults(res.items);
      setTotal(res.total);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [query, mode, filterYear, filterLang, filterQuality, filterDirectory, filterCategory]);

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

  // Refresh a single document's thumbnail after an image edit is applied
  useEffect(() => {
    const handler = (e: Event) => {
      const { id } = (e as CustomEvent<{ id: number }>).detail;
      setThumbVersions(prev => ({ ...prev, [id]: Date.now() }));
    };
    window.addEventListener("docintell:document-image-changed", handler);
    return () => window.removeEventListener("docintell:document-image-changed", handler);
  }, []);

  // Also re-search immediately when filters change (no debounce needed)
  useEffect(() => {
    if (mode !== "ask") doSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterYear, filterLang, filterQuality, filterDirectory, filterCategory]);

  // Fetch embedded doc IDs on mount and whenever a library change occurs
  useEffect(() => {
    fetchEmbeddedIds().then(data => setEmbeddedIds(new Set(data.ids))).catch(() => {});
  }, []);
  useEffect(() => {
    const handler = () => fetchEmbeddedIds().then(data => setEmbeddedIds(new Set(data.ids))).catch(() => {});
    window.addEventListener("docintell:library-changed", handler);
    return () => window.removeEventListener("docintell:library-changed", handler);
  }, []);

  // Fetch quality counts on mount and whenever the library changes
  useEffect(() => {
    fetchQualityCounts().then(setQualityCounts).catch(() => {});
  }, []);
  useEffect(() => {
    const handler = () => fetchQualityCounts().then(setQualityCounts).catch(() => {});
    window.addEventListener("docintell:library-changed", handler);
    return () => window.removeEventListener("docintell:library-changed", handler);
  }, []);

  // ── Folder browser (Explorer-style) ─────────────────────────────────────────

  const loadFolderTree = useCallback(() => {
    setFolderTreeLoading(true);
    getFolderTree().then(setFolderTree).catch(() => {}).finally(() => setFolderTreeLoading(false));
  }, []);

  useEffect(() => {
    if (layoutMode === "folders" && !folderTree) loadFolderTree();
  }, [layoutMode, folderTree, loadFolderTree]);

  useEffect(() => {
    const handler = () => { if (layoutMode === "folders") loadFolderTree(); };
    window.addEventListener("docintell:library-changed", handler);
    return () => window.removeEventListener("docintell:library-changed", handler);
  }, [layoutMode, loadFolderTree]);

  // Flattened, depth-first list of every document in the tree — used for
  // prev/next navigation in the viewer (mirrors FolderTreeView's render order).
  const flatTreeDocs = useMemo(() => {
    const out: Document[] = [];
    const walk = (node: FolderTreeNode) => {
      node.folders.forEach(walk);
      out.push(...node.documents);
    };
    if (folderTree) walk(folderTree);
    return out;
  }, [folderTree]);

  useEffect(() => {
    if (folderViewerIdx === null) { setFolderViewerDoc(null); return; }
    const doc = flatTreeDocs[folderViewerIdx];
    if (!doc) return;
    getDocument(doc.id).then(setFolderViewerDoc).catch(() => setFolderViewerDoc(doc));
  }, [folderViewerIdx, flatTreeDocs]);

  const openFolderDoc = (doc: Document) => {
    const idx = flatTreeDocs.findIndex((d) => d.id === doc.id);
    setFolderViewerIdx(idx >= 0 ? idx : null);
  };

  // ── AI ask ──────────────────────────────────────────────────────────────────

  const doAsk = useCallback(async () => {
    if (!query.trim()) return;
    setAiLoading(true);
    setAiAnswer(null);
    try {
      const res = await askDocuments(query, lang, filterYear, filterLang, depth, devMode);
      setAiAnswer(res);
    } catch {
      /* ignore */
    } finally {
      setAiLoading(false);
    }
  }, [query, lang, filterYear, filterLang, depth, devMode]);

  // ── Mode change ─────────────────────────────────────────────────────────────

  const handleModeChange = (m: SearchMode) => {
    setMode(m);
    setQuery("");
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

  // ── Dispatch quality filter docs to processing queue ──────────────────────

  const handleDispatch = () => {
    if (!filterQuality || filterQuality === "complete") return;
    const labelMap: Record<string, string> = {
      no_ocr: t.filters.qualityNoOcr,
      no_embedding: t.filters.qualityNoEmbedding,
      no_analysis: t.filters.qualityNoAnalysis,
      no_summary: t.filters.qualityNoSummary,
      no_tags: t.filters.qualityNoTags,
      no_category: t.filters.qualityNoCategory,
    };
    window.dispatchEvent(
      new CustomEvent("docintell:open-tasks-create", {
        detail: {
          taskType: "fix_quality",
          title: `Fix: ${labelMap[filterQuality] ?? filterQuality}`,
          config: { quality_filter: filterQuality },
          candidateCount: qualityCounts[filterQuality] ?? 0,
        },
      })
    );
  };

  // ── Tag / category search ────────────────────────────────────────────────────

  const handleTagSearch = (value: string) => {
    setViewerIdx(null);
    setAiViewerIdx(null);
    setFolderViewerIdx(null);
    setLayoutMode("flat");
    if (mode === "ask") setMode("search");
    setQuery(value);
  };

  const handleDirectoryFilter = (directory: string) => {
    setViewerIdx(null);
    setAiViewerIdx(null);
    setFolderViewerIdx(null);
    setLayoutMode("flat");
    if (mode === "ask") setMode("search");
    setFilterDirectory(directory);
  };

  const handleCategoryFilter = (category: string) => {
    setViewerIdx(null);
    setAiViewerIdx(null);
    setFolderViewerIdx(null);
    setLayoutMode("flat");
    if (mode === "ask") setMode("search");
    setFilterCategory(category);
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
    "/":          () => { document.querySelector<HTMLTextAreaElement>(".search-input")?.focus(); },
    "Escape":     () => {
      if (aiViewerIdx !== null) { setAiViewerIdx(null); return; }
      if (viewerIdx !== null)   { setViewerIdx(null);   return; }
      if (folderViewerIdx !== null) { setFolderViewerIdx(null); return; }
      setQuery("");
    },
    "ArrowLeft":  () => {
      if (aiViewerIdx !== null && aiViewerIdx > 0) setAiViewerIdx(aiViewerIdx - 1);
      else if (viewerIdx !== null && viewerIdx > 0) setViewerIdx(viewerIdx - 1);
      else if (folderViewerIdx !== null && folderViewerIdx > 0) setFolderViewerIdx(folderViewerIdx - 1);
    },
    "ArrowRight": () => {
      if (aiViewerIdx !== null && aiAnswer && aiViewerIdx < aiAnswer.sources.length - 1) setAiViewerIdx(aiViewerIdx + 1);
      else if (viewerIdx !== null && viewerIdx < results.length - 1) setViewerIdx(viewerIdx + 1);
      else if (folderViewerIdx !== null && folderViewerIdx < flatTreeDocs.length - 1) setFolderViewerIdx(folderViewerIdx + 1);
    },
    "1":          () => { setLayoutMode("flat"); setViewMode("list"); },
    "2":          () => { setLayoutMode("flat"); setViewMode("grid"); },
    "3":          () => setLayoutMode("folders"),
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
          <HomePageToolbar
            t={t}
            total={total}
            filterDirectory={filterDirectory}
            onClearDirectory={() => setFilterDirectory(null)}
            filterCategory={filterCategory}
            onClearCategory={() => setFilterCategory(null)}
            advancedMode={advancedMode}
            qualityCounts={qualityCounts}
            filterQuality={filterQuality}
            onFilterQuality={setFilterQuality}
            onDispatch={handleDispatch}
            syncing={syncing}
            onSync={handleSync}
            onToggleUpload={() => setShowUpload((v) => !v)}
            layoutMode={layoutMode}
            viewMode={viewMode}
            onViewMode={(m) => { setLayoutMode("flat"); setViewMode(m); }}
            onFolderMode={() => setLayoutMode("folders")}
            gridSize={gridSize}
            onCycleGridSize={cycleGridSize}
          />
        )}

        {/* Upload zone (collapsible) */}
        {showUpload && mode !== "ask" && (
          <div className="home-upload">
            <UploadZone onUploaded={() => { doSearch(); setTimeout(() => setShowUpload(false), 2000); }} />
          </div>
        )}

        {/* ── AI mode content ── */}
        {mode === "ask" && (
          <HomePageAIMode
            t={t}
            aiLoading={aiLoading}
            aiAnswer={aiAnswer}
            devMode={devMode}
            thumbVersions={thumbVersions}
            onDocClick={(i) => setAiViewerIdx(i)}
          />
        )}

        {/* ── Regular search content ── */}
        {mode !== "ask" && layoutMode === "flat" && (
          <HomePageResults
            loading={loading}
            results={results}
            query={query}
            viewMode={viewMode}
            gridSize={gridSize}
            devMode={devMode}
            embeddedIds={embeddedIds}
            thumbVersions={thumbVersions}
            onUpload={() => setShowUpload(true)}
            onOpen={(i) => setViewerIdx(i)}
            onTagClick={handleTagSearch}
            onCategoryClick={handleCategoryFilter}
          />
        )}

        {/* ── Folder browser (Explorer-style) ── */}
        {mode !== "ask" && layoutMode === "folders" && (
          <HomePageFolderResults
            loading={folderTreeLoading}
            tree={folderTree}
            viewMode={viewMode}
            gridSize={gridSize}
            devMode={devMode}
            embeddedIds={embeddedIds}
            thumbVersions={thumbVersions}
            onOpen={openFolderDoc}
            onTagClick={handleTagSearch}
            onCategoryClick={handleCategoryFilter}
          />
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
        isEmbedded={viewerDoc ? embeddedIds.has(viewerDoc.id) : undefined}
        onTagClick={handleTagSearch}
        onCategoryClick={handleCategoryFilter}
        onDirectoryClick={handleDirectoryFilter}
      />

      {/* Document viewer — AI sources */}
      <DocumentViewer
        doc={aiViewerDoc}
        onClose={() => setAiViewerIdx(null)}
        onPrev={() => setAiViewerIdx((i) => (i !== null ? i - 1 : null))}
        onNext={() => setAiViewerIdx((i) => (i !== null ? i + 1 : null))}
        hasPrev={aiViewerIdx !== null && aiViewerIdx > 0}
        hasNext={aiViewerIdx !== null && aiAnswer !== null && aiViewerIdx < aiAnswer.sources.length - 1}
        isEmbedded={aiViewerDoc ? embeddedIds.has(aiViewerDoc.id) : undefined}
        onTagClick={handleTagSearch}
        onCategoryClick={handleCategoryFilter}
        onDirectoryClick={handleDirectoryFilter}
      />

      {/* Document viewer — folder browser */}
      <DocumentViewer
        doc={folderViewerDoc}
        onClose={() => setFolderViewerIdx(null)}
        onPrev={() => setFolderViewerIdx((i) => (i !== null ? i - 1 : null))}
        onNext={() => setFolderViewerIdx((i) => (i !== null ? i + 1 : null))}
        hasPrev={folderViewerIdx !== null && folderViewerIdx > 0}
        hasNext={folderViewerIdx !== null && folderViewerIdx < flatTreeDocs.length - 1}
        isEmbedded={folderViewerDoc ? embeddedIds.has(folderViewerDoc.id) : undefined}
        onTagClick={handleTagSearch}
        onCategoryClick={handleCategoryFilter}
        onDirectoryClick={handleDirectoryFilter}
      />

      {/* Keyboard shortcuts help */}
      <KeyboardHelp open={showHelp} onClose={() => setShowHelp(false)} />
    </main>
  );
}
