import { FolderTreeView } from "../../components/documents/FolderTreeView";
import { useT } from "../../i18n";
import type { Document, FolderTreeNode, GridSize, ViewMode } from "../../types";

interface Props {
  loading: boolean;
  tree: FolderTreeNode | null;
  viewMode: ViewMode;
  gridSize: GridSize;
  devMode: boolean;
  embeddedIds: Set<number>;
  thumbVersions: Record<number, number>;
  onOpen: (doc: Document) => void;
  onTagClick: (value: string) => void;
  onCategoryClick: (category: string) => void;
}

export function HomePageFolderResults({ loading, tree, ...rest }: Props) {
  const { t } = useT();

  if (loading && !tree) {
    return (
      <div className="doc-list">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 34, borderRadius: 8 }} />
        ))}
      </div>
    );
  }

  if (!tree || (tree.folders.length === 0 && tree.documents.length === 0)) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">📂</div>
        <h2 className="empty-state-title">{t.noDocuments}</h2>
        <p className="empty-state-hint text-muted">{t.noDocumentsHint}</p>
      </div>
    );
  }

  return <FolderTreeView node={tree} {...rest} />;
}
