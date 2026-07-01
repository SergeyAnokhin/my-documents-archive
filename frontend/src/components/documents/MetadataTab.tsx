import { Tag, X, Filter, FolderOpen } from "lucide-react";
import type { Document } from "../../types";
import { useT } from "../../i18n";
import { TypePicker, formatTypeName } from "./TypePicker";

function formatDate(iso?: string) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}

interface Props {
  doc: Document;
  t: ReturnType<typeof useT>["t"];
  displayType?: string;
  displayManual?: boolean;
  displayTags: string[];
  displayDate?: string | null;
  directory: string | null;
  onTagClick?: (value: string) => void;
  onCategoryClick?: (category: string) => void;
  onDirectoryClick?: (directory: string) => void;
  onRemoveTag: (tag: string) => void;
  onRemoveDate: () => void;
  onTypeSaved: (type: string) => void;
}

export function MetadataTab({
  doc, t, displayType, displayManual, displayTags, displayDate, directory,
  onTagClick, onCategoryClick, onDirectoryClick, onRemoveTag, onRemoveDate, onTypeSaved,
}: Props) {
  return (
    <div className="viewer-meta-list">
      {doc.summary && <p className="viewer-summary">{doc.summary}</p>}

      <div className="viewer-meta-row">
        <span className="viewer-meta-label">Type</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <TypePicker
            docId={doc.id}
            currentType={displayType}
            isManual={displayManual}
            onSaved={onTypeSaved}
          />
          {onCategoryClick && displayType && displayType !== "unclassified" && displayType !== "other" && (
            <button
              className="icon-btn"
              style={{ width: 24, height: 24, flexShrink: 0 }}
              onClick={() => onCategoryClick(displayType)}
              title={`${t.filters.type}: ${formatTypeName(displayType)}`}
            >
              <Filter size={12} />
            </button>
          )}
        </div>
      </div>

      {displayTags.length > 0 && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label"><Tag size={13}/> Tags</span>
          <div className="viewer-tags">
            {displayTags.map((tag) => (
              <span
                key={tag}
                className={`tag${onTagClick ? " tag-clickable" : ""}`}
                onClick={onTagClick ? () => onTagClick(tag) : undefined}
                title={onTagClick ? `Search: ${tag}` : undefined}
              >
                {tag}
                <button className="tag-remove" onClick={(e) => { e.stopPropagation(); onRemoveTag(tag); }} title="Remove tag">
                  <X size={10} />
                </button>
              </span>
            ))}
          </div>
        </div>
      )}
      {doc.language && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Language</span>
          <span>{doc.language}</span>
        </div>
      )}
      {doc.organization && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Organization</span>
          <span>{doc.organization}</span>
        </div>
      )}
      {(doc.person_first_name || doc.person_last_name) && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Person</span>
          <span>{[doc.person_first_name, doc.person_last_name].filter(Boolean).join(" ")}</span>
        </div>
      )}
      {displayDate && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Date</span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {formatDate(displayDate)}
            <button className="tag-remove" onClick={onRemoveDate} title="Remove date">
              <X size={10} />
            </button>
          </span>
        </div>
      )}
      {doc.amount != null && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Amount</span>
          <span>{doc.amount} {doc.amount_currency ?? ""}</span>
        </div>
      )}

      <div className="viewer-meta-divider" />

      {doc.relative_path && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Path</span>
          <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
            <span className="text-mono text-sm viewer-meta-path">{doc.relative_path}</span>
            {onDirectoryClick && directory && (
              <button
                className="icon-btn"
                style={{ width: 24, height: 24, flexShrink: 0 }}
                onClick={() => onDirectoryClick(directory)}
                title={`${t.filters.folder}: ${directory}`}
              >
                <FolderOpen size={12} />
              </button>
            )}
          </div>
        </div>
      )}
      <div className="viewer-meta-row">
        <span className="viewer-meta-label">Filename</span>
        <span className="text-mono text-sm">{doc.filename}</span>
      </div>
      {doc.added_at && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Added</span>
          <span>{formatDate(doc.added_at)}</span>
        </div>
      )}
      {doc.file_size && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Size</span>
          <span>{(doc.file_size / 1024).toFixed(1)} KB</span>
        </div>
      )}
    </div>
  );
}
