import { LayoutList, LayoutGrid, RefreshCw, Plus, ChevronDown, SendHorizonal, FolderOpen, Filter, X } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { FilterDropdown } from "../../components/search/FilterDropdown";
import { useT } from "../../i18n";
import type { GridSize, ViewMode } from "../../types";

interface Props {
  t: ReturnType<typeof useT>["t"];
  total: number;
  filterDirectory: string | null;
  onClearDirectory: () => void;
  filterCategory: string | null;
  onClearCategory: () => void;
  advancedMode: boolean;
  qualityCounts: Record<string, number>;
  filterQuality: string | null;
  onFilterQuality: (value: string | null) => void;
  onDispatch: () => void;
  syncing: boolean;
  onSync: () => void;
  onToggleUpload: () => void;
  viewMode: ViewMode;
  onViewMode: (mode: ViewMode) => void;
  gridSize: GridSize;
  onCycleGridSize: () => void;
}

export function HomePageToolbar({
  t, total, filterDirectory, onClearDirectory, filterCategory, onClearCategory,
  advancedMode, qualityCounts, filterQuality, onFilterQuality, onDispatch,
  syncing, onSync, onToggleUpload, viewMode, onViewMode, gridSize, onCycleGridSize,
}: Props) {
  return (
    <div className="home-toolbar">
      <div className="toolbar-left">
        <span className="toolbar-count text-sm text-muted">
          {total > 0 ? `${total} documents` : ""}
        </span>
        {filterDirectory && (
          <span className="tag">
            <FolderOpen size={11} />
            {t.filters.folder}: {filterDirectory}
            <button className="tag-remove" onClick={onClearDirectory} title="Remove filter">
              <X size={10} />
            </button>
          </span>
        )}
        {filterCategory && (
          <span className="tag">
            <Filter size={11} />
            {t.filters.type}: {filterCategory}
            <button className="tag-remove" onClick={onClearCategory} title="Remove filter">
              <X size={10} />
            </button>
          </span>
        )}
        {advancedMode && (
          <>
            <FilterDropdown
              label={t.filters.quality}
              clearLabel={t.filters.allDocuments}
              options={[
                { value: "no_ocr",       label: t.filters.qualityNoOcr,       count: qualityCounts["no_ocr"] },
                { value: "no_embedding", label: t.filters.qualityNoEmbedding, count: qualityCounts["no_embedding"] },
                { value: "no_analysis",  label: t.filters.qualityNoAnalysis,  count: qualityCounts["no_analysis"] },
                { value: "no_summary",   label: t.filters.qualityNoSummary,   count: qualityCounts["no_summary"] },
                { value: "no_tags",      label: t.filters.qualityNoTags,      count: qualityCounts["no_tags"] },
                { value: "no_category",  label: t.filters.qualityNoCategory,  count: qualityCounts["no_category"] },
                { value: "complete",     label: t.filters.qualityComplete },
              ]}
              value={filterQuality}
              onSelect={onFilterQuality}
            />
            {filterQuality && filterQuality !== "complete" && (
              <Button
                variant="ghost"
                size="sm"
                icon={<SendHorizonal size={13} />}
                onClick={onDispatch}
              >
                {t.filters.qualityDispatch}
              </Button>
            )}
          </>
        )}
      </div>
      <div className="toolbar-right">
        <Button
          variant="ghost" size="sm"
          icon={<RefreshCw size={14} />}
          loading={syncing}
          onClick={onSync}
        >
          {t.syncButton}
        </Button>
        <Button
          variant="secondary" size="sm"
          icon={<Plus size={14} />}
          onClick={onToggleUpload}
        >
          {t.uploadTitle}
        </Button>
        <div className="view-toggle">
          <button
            className={`view-btn${viewMode === "list" ? " active" : ""}`}
            onClick={() => onViewMode("list")}
            title={t.viewList}
          >
            <LayoutList size={16} />
          </button>
          <button
            className={`view-btn${viewMode === "grid" ? " active" : ""}`}
            onClick={() => onViewMode("grid")}
            title={t.viewGrid}
          >
            <LayoutGrid size={16} />
          </button>
          {viewMode === "grid" && (
            <button className="view-btn" onClick={onCycleGridSize} title="Change grid size">
              <ChevronDown size={14} />
              <span className="text-xs">{gridSize.toUpperCase()}</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
