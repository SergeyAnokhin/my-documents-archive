import type { Document } from "../../types";
import { useT } from "../../i18n";

interface Props {
  doc: Document;
  t: ReturnType<typeof useT>["t"];
}

export function TextTab({ doc, t }: Props) {
  return (
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
  );
}
