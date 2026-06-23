import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download, ChevronLeft, ChevronRight, FileText, Tag, RefreshCw, FlaskConical } from "lucide-react";
import type { Document } from "../../types";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";
import { reclassifyDocument, reindexDocument } from "../../api/documents";
import "./DocumentViewer.css";

interface Props {
  doc: Document | null;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
}

function formatDate(iso?: string) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}

export function DocumentViewer({ doc, onClose, onPrev, onNext, hasPrev, hasNext }: Props) {
  const { t } = useT();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<"preview" | "text" | "details" | "dev">("preview");
  const [devMsg, setDevMsg] = useState("");
  const [devLoading, setDevLoading] = useState<"reindex" | "reclassify" | null>(null);

  const flashDev = (msg: string) => { setDevMsg(msg); setTimeout(() => setDevMsg(""), 4000); };

  const handleReindex = async () => {
    if (!doc) return;
    setDevLoading("reindex");
    try {
      await reindexDocument(doc.id);
      flashDev(t.reindexStarted);
    } catch {
      flashDev(t.error);
    } finally {
      setDevLoading(null);
    }
  };

  const handleReclassify = async () => {
    if (!doc) return;
    setDevLoading("reclassify");
    try {
      await reclassifyDocument(doc.id);
      flashDev(t.reclassifyStarted);
    } catch {
      flashDev(t.error);
    } finally {
      setDevLoading(null);
    }
  };

  if (!doc) return null;

  const thumbUrl = doc.thumbnail_path ? `/thumbnails/${doc.id}.jpg` : null;

  return (
    <Modal open={!!doc} onClose={onClose} size="xl" title={doc.filename}>
      <div className="viewer-layout">
        {/* Left — preview */}
        <div className="viewer-preview">
          {thumbUrl ? (
            <img src={thumbUrl} alt={doc.filename} className="viewer-thumb" />
          ) : (
            <div className="viewer-thumb-placeholder">
              <FileText size={64} />
            </div>
          )}

          {/* Nav arrows */}
          <div className="viewer-nav">
            <button
              className="viewer-nav-btn"
              onClick={onPrev}
              disabled={!hasPrev}
              aria-label="Previous document"
            >
              <ChevronLeft size={20} />
            </button>
            <button
              className="viewer-nav-btn"
              onClick={onNext}
              disabled={!hasNext}
              aria-label="Next document"
            >
              <ChevronRight size={20} />
            </button>
          </div>
        </div>

        {/* Right — info */}
        <div className="viewer-info">
          {/* Tabs */}
          <div className="viewer-tabs">
            {(["preview", "text", "details", "dev"] as const).map((tab) => (
              <button
                key={tab}
                className={`viewer-tab${activeTab === tab ? " active" : ""}`}
                onClick={() => setActiveTab(tab)}
              >
                {tab === "preview" ? "Preview"
                  : tab === "text" ? t.recognizedText
                  : tab === "details" ? t.metadata
                  : t.devMode}
              </button>
            ))}
          </div>

          <div className="viewer-tab-body">
            {activeTab === "preview" && (
              <div className="viewer-meta-list">
                {doc.summary && <p className="viewer-summary">{doc.summary}</p>}
                {doc.document_type && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Type</span>
                    <span className="tag">{doc.document_type}</span>
                  </div>
                )}
                {doc.tags && doc.tags.length > 0 && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label"><Tag size={13}/> Tags</span>
                    <div className="viewer-tags">
                      {doc.tags.map((tag) => <span key={tag} className="tag">{tag}</span>)}
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
                {doc.amount != null && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Amount</span>
                    <span>{doc.amount} {doc.amount_currency ?? ""}</span>
                  </div>
                )}
              </div>
            )}

            {activeTab === "text" && (
              <div className="viewer-ocr-text text-sm">
                {doc.vision_description && (
                  <div style={{ marginBottom: 16 }}>
                    <p className="text-xs text-muted" style={{ marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      AI Vision
                    </p>
                    <p style={{ lineHeight: 1.6 }}>{doc.vision_description}</p>
                    <hr style={{ margin: "12px 0", borderColor: "var(--color-border)" }} />
                  </div>
                )}
                <p className="text-xs text-muted" style={{ marginBottom: 6, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  OCR
                </p>
                <div className="text-mono">
                  {doc.ocr_text || <em className="text-muted">{t.noSummary}</em>}
                </div>
              </div>
            )}

            {activeTab === "details" && (
              <div className="viewer-meta-list">
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">Filename</span>
                  <span className="text-mono text-sm">{doc.filename}</span>
                </div>
                {doc.document_date && (
                  <div className="viewer-meta-row">
                    <span className="viewer-meta-label">Document date</span>
                    <span>{formatDate(doc.document_date)}</span>
                  </div>
                )}
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
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">OCR</span>
                  <span className={`status-dot ${doc.ocr_status}`} style={{ marginRight: 6 }} />
                  <span className="text-sm">{t.status[doc.ocr_status as keyof typeof t.status]}</span>
                </div>
              </div>
            )}

            {activeTab === "dev" && (
              <div className="viewer-meta-list">
                <p className="text-xs text-muted" style={{ marginBottom: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {t.pipelineStatus}
                </p>

                {/* OCR */}
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">OCR</span>
                  <span className={`status-dot ${doc.ocr_status}`} style={{ marginRight: 6 }} />
                  <span className="text-sm">{doc.ocr_status}</span>
                </div>
                {doc.ocr_error && (
                  <p className="text-xs" style={{ color: "var(--color-error, #c0392b)", marginBottom: 8, marginLeft: 8 }}>
                    {doc.ocr_error}
                  </p>
                )}

                {/* Vision */}
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">Vision</span>
                  <span className={`status-dot ${doc.vision_status}`} style={{ marginRight: 6 }} />
                  <span className="text-sm">{doc.vision_status}</span>
                </div>
                {doc.vision_error && (
                  <p className="text-xs" style={{ color: "var(--color-error, #c0392b)", marginBottom: 8, marginLeft: 8 }}>
                    {doc.vision_error}
                  </p>
                )}

                {/* Analysis */}
                <div className="viewer-meta-row">
                  <span className="viewer-meta-label">Analysis</span>
                  <span className={`status-dot ${doc.analysis_status}`} style={{ marginRight: 6 }} />
                  <span className="text-sm">{doc.analysis_status}</span>
                </div>
                {doc.analysis_error && (
                  <p className="text-xs" style={{ color: "var(--color-error, #c0392b)", marginBottom: 8, marginLeft: 8 }}>
                    {doc.analysis_error}
                  </p>
                )}

                {/* Costs */}
                {((doc.api_cost_vision ?? 0) > 0 || (doc.api_cost_analysis ?? 0) > 0) && (
                  <div className="viewer-meta-row" style={{ marginTop: 8 }}>
                    <span className="viewer-meta-label">API cost</span>
                    <span className="text-xs text-muted">
                      vision ${(doc.api_cost_vision ?? 0).toFixed(5)} · analysis ${(doc.api_cost_analysis ?? 0).toFixed(5)}
                    </span>
                  </div>
                )}

                {/* Actions */}
                <div style={{ marginTop: 16, display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RefreshCw size={13} />}
                    loading={devLoading === "reclassify"}
                    onClick={handleReclassify}
                  >
                    {t.reclassify}
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RefreshCw size={13} />}
                    loading={devLoading === "reindex"}
                    onClick={handleReindex}
                  >
                    {t.reindex}
                  </Button>
                </div>
                {devMsg && <p className="text-xs text-muted" style={{ marginTop: 8 }}>{devMsg}</p>}
              </div>
            )}
          </div>

          {/* Download */}
          <div className="viewer-actions">
            <Button
              variant="primary"
              size="sm"
              icon={<FlaskConical size={14} />}
              onClick={() => navigate(`/lab/${doc.id}`)}
            >
              {t.labMode}
            </Button>
            <a href={`/api/documents/${doc.id}/download`} download>
              <Button variant="secondary" size="sm" icon={<Download size={14} />}>
                {t.download}
              </Button>
            </a>
          </div>
        </div>
      </div>
    </Modal>
  );
}
