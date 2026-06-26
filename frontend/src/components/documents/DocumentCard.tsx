import { FileText, Calendar, Tag, Sparkles, ScanText, Cpu } from "lucide-react";
import type { Document } from "../../types";
import { useT } from "../../i18n";
import { iconForType } from "./typeIcons";
import { formatTypeName } from "./TypePicker";
import "./DocumentCard.css";

// Highest processing tier a document has reached, in increasing order of
// "richness": pending → local OCR (tesseract/easyocr) → AI text recognition →
// full AI analysis. Drives the ProcessingBadge indicator.
type ProcLevel = "pending" | "error" | "tesseract" | "easyocr" | "local" | "ai-ocr" | "analyzed";

/** An ocr_model that names neither local engine was produced by an AI model. */
function isAiOcr(model?: string): boolean {
  if (!model) return false;
  const m = model.toLowerCase();
  return !m.includes("tesseract") && !m.includes("easyocr");
}

function processingLevel(doc: Document): ProcLevel {
  if (doc.analysis_status === "done") return "analyzed";
  if (doc.vision_status === "done" || (doc.ocr_status === "done" && isAiOcr(doc.ocr_model)))
    return "ai-ocr";
  if (doc.ocr_status === "done") {
    const m = (doc.ocr_model || "").toLowerCase();
    if (m.includes("easyocr")) return "easyocr";
    if (m.includes("tesseract")) return "tesseract";
    return "local"; // OCR'd before engine tracking existed
  }
  if (doc.ocr_status === "error" || doc.vision_status === "error" || doc.analysis_status === "error")
    return "error";
  return "pending";
}

/** Single tiered indicator: a colored dot for local OCR, a violet icon for AI
 *  recognition, and a filled gradient sparkle badge once fully AI-analyzed. */
function ProcessingBadge({ doc, className = "" }: { doc: Document; className?: string }) {
  const { t } = useT();
  const level = processingLevel(doc);
  const title = t.proc[level === "ai-ocr" ? "aiOcr" : level];

  if (level === "analyzed")
    return (
      <span className={`proc proc-analyzed ${className}`} title={title} aria-label={title}>
        <Sparkles size={11} strokeWidth={2.5} />
      </span>
    );
  if (level === "ai-ocr")
    return (
      <span className={`proc proc-ai-ocr ${className}`} title={title} aria-label={title}>
        <ScanText size={13} strokeWidth={2.25} />
      </span>
    );
  if (level === "easyocr")
    return (
      <span className={`proc proc-easyocr ${className}`} title={title} aria-label={title}>
        <Cpu size={12} strokeWidth={2} />
      </span>
    );
  return <span className={`proc proc-dot ${level} ${className}`} title={title} aria-label={title} />;
}

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

function TypeIcon({ type, size, className }: { type: string; size: number; className: string }) {
  const Icon = iconForType(type);
  return (
    <span className={className} title={formatTypeName(type)} aria-label={formatTypeName(type)}>
      <Icon size={size} />
    </span>
  );
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
              <ProcessingBadge doc={doc} />
              {doc.document_type && <TypeIcon type={doc.document_type} size={18} className="doc-type-icon" />}
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
        {doc.document_type && <TypeIcon type={doc.document_type} size={16} className="doc-grid-type-icon" />}
        <ProcessingBadge doc={doc} className="doc-grid-status" />
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
