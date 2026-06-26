import { FileText, Calendar, Tag } from "lucide-react";
import type { Document } from "../../types";
import { useT } from "../../i18n";
import "./DocumentCard.css";

interface Props {
  doc: Document;
  highlight?: string;
  onClick: () => void;
  mode: "list" | "grid";
  gridSize?: "sm" | "md" | "lg" | "xl";
}

function formatDate(iso?: string): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function Thumbnail({ doc }: { doc: Document }) {
  if (doc.thumbnail_path) {
    const v = doc.updated_at ? `?v=${new Date(doc.updated_at).getTime()}` : "";
    const url = `/thumbnails/${doc.id}.jpg${v}`;
    return <img src={url} alt="" className="doc-thumb-img" loading="lazy" />;
  }
  return (
    <div className="doc-thumb-placeholder">
      <FileText size={28} />
    </div>
  );
}

export function DocumentCard({ doc, highlight, onClick, mode, gridSize = "md" }: Props) {
  const { t } = useT();
  const date = formatDate(doc.document_date || doc.added_at);

  if (mode === "list") {
    return (
      <article className="doc-list-item" onClick={onClick} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onClick()}>
        <div className="doc-list-thumb">
          <Thumbnail doc={doc} />
        </div>
        <div className="doc-list-body">
          <div className="doc-list-top">
            <span className="doc-filename truncate">{doc.filename}</span>
            <div className="doc-list-meta">
              {date && <span className="doc-date text-sm text-muted"><Calendar size={12} /> {date}</span>}
              <span className={`status-dot ${doc.ocr_status}`} title={t.status[doc.ocr_status as keyof typeof t.status]} />
            </div>
          </div>
          {doc.document_type && (
            <span className="tag">{doc.document_type}</span>
          )}
          {(highlight || doc.summary) && (
            <p className="doc-snippet text-sm text-muted">
              {highlight || doc.summary}
            </p>
          )}
          {doc.tags && doc.tags.length > 0 && (
            <div className="doc-tags">
              {doc.tags.slice(0, 5).map((tag) => (
                <span key={tag} className="tag"><Tag size={10} />{tag}</span>
              ))}
            </div>
          )}
        </div>
      </article>
    );
  }

  // Grid mode
  return (
    <article
      className={`doc-grid-item doc-grid-${gridSize}`}
      onClick={onClick}
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
    >
      <div className="doc-grid-thumb">
        <Thumbnail doc={doc} />
        <span className={`doc-grid-status status-dot ${doc.ocr_status}`} />
      </div>
      <div className="doc-grid-footer">
        <span className="doc-filename truncate text-sm">{doc.filename}</span>
        {gridSize !== "sm" && date && (
          <span className="doc-date text-xs text-muted">{date}</span>
        )}
        {gridSize === "xl" && doc.summary && (
          <p className="doc-snippet text-xs text-muted">{doc.summary}</p>
        )}
      </div>
    </article>
  );
}
