import { useState } from "react";
import { ChevronRight, ChevronDown, Folder, FolderOpen } from "lucide-react";
import { DocumentCard } from "./DocumentCard";
import type { Document, FolderTreeNode, GridSize, ViewMode } from "../../types";
import "./FolderTreeView.css";

interface CommonProps {
  viewMode: ViewMode;
  gridSize: GridSize;
  devMode: boolean;
  embeddedIds: Set<number>;
  thumbVersions: Record<number, number>;
  onOpen: (doc: Document) => void;
  onTagClick: (value: string) => void;
  onCategoryClick: (category: string) => void;
}

/** Root of the Explorer-style folder browser: renders the library root's
 *  subfolders and any documents sitting directly in the library root. */
export function FolderTreeView({ node, ...rest }: CommonProps & { node: FolderTreeNode }) {
  return (
    <div className="folder-tree">
      {node.folders.map((f) => (
        <FolderNode key={f.path} node={f} depth={0} {...rest} />
      ))}
      {node.documents.length > 0 && <FolderDocs docs={node.documents} depth={0} {...rest} />}
    </div>
  );
}

function FolderNode({ node, depth, ...rest }: CommonProps & { node: FolderTreeNode; depth: number }) {
  const [open, setOpen] = useState(false);
  const hasChildren = node.folders.length > 0 || node.documents.length > 0;

  return (
    <div className="folder-node">
      <button
        type="button"
        className="folder-row"
        style={{ paddingLeft: `${depth * 20 + 8}px` }}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="folder-chevron">
          {hasChildren ? (
            open ? <ChevronDown size={14} /> : <ChevronRight size={14} />
          ) : (
            <span className="folder-chevron-spacer" />
          )}
        </span>
        <span className="folder-icon">
          {open ? <FolderOpen size={18} /> : <Folder size={18} />}
        </span>
        <span className="folder-name truncate">{node.name}</span>
        {node.total_count > 0 && <span className="folder-count text-xs text-muted">{node.total_count}</span>}
      </button>
      {open && (
        <div className="folder-children">
          {node.folders.map((f) => (
            <FolderNode key={f.path} node={f} depth={depth + 1} {...rest} />
          ))}
          {node.documents.length > 0 && <FolderDocs docs={node.documents} depth={depth + 1} {...rest} />}
        </div>
      )}
    </div>
  );
}

function FolderDocs({
  docs, depth, viewMode, gridSize, devMode, embeddedIds, thumbVersions, onOpen, onTagClick, onCategoryClick,
}: CommonProps & { docs: Document[]; depth: number }) {
  const style = { paddingLeft: `${depth * 20 + 28}px` };

  if (viewMode === "list") {
    return (
      <div className="folder-docs doc-list" style={style}>
        {docs.map((doc) => (
          <DocumentCard
            key={doc.id}
            doc={doc}
            mode="list"
            onClick={() => onOpen(doc)}
            onTagClick={onTagClick}
            onCategoryClick={onCategoryClick}
            thumbVersion={thumbVersions[doc.id]}
            devMode={devMode}
            isEmbedded={embeddedIds.has(doc.id)}
          />
        ))}
      </div>
    );
  }

  return (
    <div className={`folder-docs doc-grid doc-grid-size-${gridSize}`} style={style}>
      {docs.map((doc) => (
        <DocumentCard
          key={doc.id}
          doc={doc}
          mode="grid"
          gridSize={gridSize}
          onClick={() => onOpen(doc)}
          onTagClick={onTagClick}
          onCategoryClick={onCategoryClick}
          thumbVersion={thumbVersions[doc.id]}
          devMode={devMode}
          isEmbedded={embeddedIds.has(doc.id)}
        />
      ))}
    </div>
  );
}
