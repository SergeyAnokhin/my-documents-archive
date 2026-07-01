import { Plus } from "lucide-react";
import { DocumentCard } from "../../components/documents/DocumentCard";
import { Button } from "../../components/ui/Button";
import { useT } from "../../i18n";
import type { GridSize, SearchResult, ViewMode } from "../../types";

interface Props {
  loading: boolean;
  results: SearchResult[];
  query: string;
  viewMode: ViewMode;
  gridSize: GridSize;
  devMode: boolean;
  embeddedIds: Set<number>;
  thumbVersions: Record<number, number>;
  onUpload: () => void;
  onOpen: (index: number) => void;
  onTagClick: (value: string) => void;
  onCategoryClick: (category: string) => void;
}

export function HomePageResults({
  loading, results, query, viewMode, gridSize, devMode, embeddedIds, thumbVersions,
  onUpload, onOpen, onTagClick, onCategoryClick,
}: Props) {
  if (loading) return <DocumentSkeleton viewMode={viewMode} gridSize={gridSize} />;
  if (results.length === 0) return <EmptyState query={query} onUpload={onUpload} />;

  if (viewMode === "list") {
    return (
      <div className="doc-list">
        {results.map((r, i) => (
          <DocumentCard
            key={r.document.id}
            doc={r.document}
            highlight={r.highlight}
            mode="list"
            onClick={() => onOpen(i)}
            onTagClick={onTagClick}
            onCategoryClick={onCategoryClick}
            thumbVersion={thumbVersions[r.document.id]}
            devMode={devMode}
            isEmbedded={embeddedIds.has(r.document.id)}
            score={r.score > 0 ? r.score : undefined}
          />
        ))}
      </div>
    );
  }

  return (
    <div className={`doc-grid doc-grid-size-${gridSize}`}>
      {results.map((r, i) => (
        <DocumentCard
          key={r.document.id}
          doc={r.document}
          mode="grid"
          gridSize={gridSize}
          onClick={() => onOpen(i)}
          onTagClick={onTagClick}
          onCategoryClick={onCategoryClick}
          thumbVersion={thumbVersions[r.document.id]}
          devMode={devMode}
          isEmbedded={embeddedIds.has(r.document.id)}
          score={r.score > 0 ? r.score : undefined}
        />
      ))}
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
