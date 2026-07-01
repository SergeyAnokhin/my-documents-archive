import { RefreshCw, Waypoints } from "lucide-react";
import type { Document } from "../../types";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";

interface Props {
  doc: Document;
  t: ReturnType<typeof useT>["t"];
  isEmbedded?: boolean;
  devLoading: "reindex" | "reclassify" | null;
  devMsg: string;
  onReclassify: () => void;
  onReindex: () => void;
}

export function DevTab({ doc, t, isEmbedded, devLoading, devMsg, onReclassify, onReindex }: Props) {
  return (
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

      {/* Embedding status */}
      <div className="viewer-meta-row">
        <span className="viewer-meta-label">Embedding</span>
        {isEmbedded === undefined ? (
          <span className="text-sm text-muted">—</span>
        ) : isEmbedded ? (
          <span className="text-sm" style={{ color: "#0d9488", display: "flex", alignItems: "center", gap: 4 }}>
            <Waypoints size={13} /> indexed
          </span>
        ) : (
          <span className="text-sm text-muted">not indexed</span>
        )}
      </div>

      {/* OCR model attribution */}
      {doc.ocr_model && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">{t.lab.ocrModel}</span>
          <span className="text-sm text-mono">{doc.ocr_model}</span>
        </div>
      )}

      {/* Classification info */}
      {doc.classification_source && (
        <div className="viewer-meta-row">
          <span className="viewer-meta-label">Classification</span>
          <span className="text-sm text-muted">
            {doc.classification_source}
            {doc.classification_confidence != null && (
              <> · {Math.round(doc.classification_confidence * 100)}% conf</>
            )}
          </span>
        </div>
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
          onClick={onReclassify}
        >
          {t.reclassify}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw size={13} />}
          loading={devLoading === "reindex"}
          onClick={onReindex}
        >
          {t.reindex}
        </Button>
      </div>
      {devMsg && <p className="text-xs text-muted" style={{ marginTop: 8 }}>{devMsg}</p>}
    </div>
  );
}
