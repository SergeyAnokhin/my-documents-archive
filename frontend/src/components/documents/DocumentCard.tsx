import { FileText, Calendar, Tag, Sparkles, ScanText, Cpu, Waypoints } from "lucide-react";
import type { Document } from "../../types";
import { useT } from "../../i18n";
import { iconForType, labelForType, isWordDoc, isTextDoc } from "./typeIcons";
import { formatTypeName } from "./TypePicker";
import "./DocumentCard.css";

// Highest processing tier a document has reached, in increasing order of
// "richness": pending → local OCR (tesseract/easyocr) → AI text recognition →
// full AI analysis. Drives the ProcessingBadge indicator.
type ProcLevel = "pending" | "error" | "tesseract" | "easyocr" | "local" | "ai-ocr" | "analyzed";

/** An ocr_model that names neither local engine nor native (.docx) extraction
 *  was produced by an AI model. */
function isAiOcr(model?: string): boolean {
  if (!model) return false;
  const m = model.toLowerCase();
  return !m.includes("tesseract") && !m.includes("easyocr") && m !== "native";
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

function EmbeddedBadge({ className = "" }: { className?: string }) {
  return (
    <span className={`emb-badge ${className}`} title="Vector embedding built" aria-label="Embedded">
      <Waypoints size={12} strokeWidth={2.5} />
    </span>
  );
}

function ScoreChip({ score, className = "" }: { score: number; className?: string }) {
  const pct = Math.round(score * 100);
  return (
    <span className={`score-chip ${className}`} title={`Semantic similarity: ${(score * 100).toFixed(1)}%`}>
      {pct}%
    </span>
  );
}

interface Props {
  doc: Document;
  highlight?: string;
  onClick: () => void;
  onTagClick?: (value: string) => void;
  onCategoryClick?: (category: string) => void;
  mode: "list" | "grid";
  gridSize?: "sm" | "md" | "lg" | "xl";
  thumbVersion?: number;
  devMode?: boolean;
  isEmbedded?: boolean;
  score?: number;
}

function formatDate(iso?: string): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function TypeIcon({ type, size, className }: { type: string; size: number; className: string }) {
  const { lang } = useT();
  const Icon = iconForType(type);
  const label = labelForType(type, lang);
  return (
    <span className={className} title={label} aria-label={label}>
      <Icon size={size} />
    </span>
  );
}

function Thumbnail({ doc, thumbVersion, mode }: { doc: Document; thumbVersion?: number; mode?: "list" | "grid" }) {
  if (doc.thumbnail_path) {
    const v = thumbVersion ?? (doc.updated_at ? new Date(doc.updated_at).getTime() : undefined);
    const filename = doc.thumbnail_path.split(/[/\\]/).pop();
    const url = `/thumbnails/${filename}${v ? `?v=${v}` : ""}`;
    return <img src={url} alt="" className="doc-thumb-img" loading="lazy" />;
  }
  // .docx/.txt have no visual page to thumbnail — show the AI title large instead of a bare icon
  if (mode === "grid" && (isWordDoc(doc.mime_type) || isTextDoc(doc.mime_type)) && doc.title) {
    return (
      <div className="doc-thumb-placeholder doc-thumb-title">
        <span className="doc-thumb-title-text">{doc.title}</span>
      </div>
    );
  }
  return (
    <div className="doc-thumb-placeholder">
      <FileText size={28} className={isWordDoc(doc.mime_type) ? "icon-word" : ""} />
    </div>
  );
}

export function DocumentCard({ doc, highlight, onClick, onTagClick, onCategoryClick, mode, gridSize = "md", thumbVersion, devMode, isEmbedded, score }: Props) {
  const { t, lang } = useT();
  const date = formatDate(doc.document_date || doc.added_at);
  const showScore = score !== undefined && score > 0;

  if (mode === "list") {
    return (
      <article className="doc-list-item" onClick={onClick} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onClick()}>
        <div className="doc-list-thumb">
          <Thumbnail doc={doc} thumbVersion={thumbVersion} />
        </div>
        <div className="doc-list-body">
          <div className="doc-list-top">
            <span className="doc-filename truncate">{doc.title || doc.filename}</span>
            <div className="doc-list-meta">
              {date && <span className="doc-date text-sm text-muted"><Calendar size={12} /> {date}</span>}
              {showScore && <ScoreChip score={score} />}
              <ProcessingBadge doc={doc} />
              {isEmbedded && <EmbeddedBadge />}
              {doc.document_type && <TypeIcon type={doc.document_type} size={27} className="doc-type-icon" />}
            </div>
          </div>
          {doc.document_type && (
            <span
              className={`tag${onCategoryClick ? " tag-clickable" : ""}`}
              onClick={onCategoryClick ? (e) => { e.stopPropagation(); onCategoryClick(doc.document_type!); } : undefined}
              title={onCategoryClick ? `${t.filters.type}: ${labelForType(doc.document_type, lang)}` : undefined}
            >
              {labelForType(doc.document_type, lang)}
            </span>
          )}
          {(highlight || doc.summary) && (
            <p className="doc-snippet text-sm text-muted">
              {highlight || doc.summary}
            </p>
          )}
          {doc.tags && doc.tags.length > 0 && (
            <div className="doc-tags">
              {doc.tags.slice(0, 5).map((tag) => (
                <span
                  key={tag}
                  className={`tag${onTagClick ? " tag-clickable" : ""}`}
                  onClick={onTagClick ? (e) => { e.stopPropagation(); onTagClick(tag); } : undefined}
                  title={onTagClick ? `Search: ${tag}` : undefined}
                >
                  <Tag size={10} />{tag}
                </span>
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
        <Thumbnail doc={doc} thumbVersion={thumbVersion} mode="grid" />
        {doc.document_type && <TypeIcon type={doc.document_type} size={24} className="doc-grid-type-icon" />}
        {showScore && <ScoreChip score={score} className="score-chip-thumb" />}
        <div className="doc-grid-badges">
          {isEmbedded && <EmbeddedBadge className="doc-grid-emb" />}
          <ProcessingBadge doc={doc} className="doc-grid-status" />
        </div>
      </div>
      <div className="doc-grid-footer">
        <span className="doc-filename truncate text-sm">{(isWordDoc(doc.mime_type) || isTextDoc(doc.mime_type)) ? doc.filename : (doc.title || doc.filename)}</span>
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
