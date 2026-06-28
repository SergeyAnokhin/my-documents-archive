import { Maximize2, X, Save, Trophy } from "lucide-react";
import { useT } from "../../i18n";
import type { LabResult } from "../../types";
import { formatMs } from "./labUtils";
import { FieldChips } from "./FieldChips";

/** List of OCR/vision transcription results with save/expand/remove actions. */
export function ResultsList({
  results,
  bestLabels,
  savingId,
  savedId,
  onSave,
  onExpand,
  onRemove,
  onFieldRemove,
}: {
  results: LabResult[];
  bestLabels: Set<string>;
  savingId: string | null;
  savedId: string | null;
  onSave: (r: LabResult) => void;
  onExpand: (r: LabResult) => void;
  onRemove: (id: string) => void;
  onFieldRemove?: (resultId: string, fieldKey: string) => void;
}) {
  const { t } = useT();
  const lab = t.lab;

  if (results.length === 0) {
    return <p className="text-xs text-muted">{lab.emptyResults}</p>;
  }

  return (
    <div className="lab-results">
      {results.map(r => {
        const isBest = bestLabels.has(r.label);
        const isSaving = savingId === r.id;
        const isSaved = savedId === r.id;
        return (
          <div key={r.id} className={`lab-card${isBest ? " best" : ""}`}>
            <div className="lab-card-head">
              <span className={`lab-kind ${r.kind}`}>{r.kind === "ocr" ? "OCR" : "AI"}</span>
              <span className="lab-card-label">{r.label}</span>
              {isBest && <Trophy size={13} className="lab-best-icon" />}
              <span className="lab-card-meta">
                {r.text.length} {lab.chars} · {formatMs(r.ms)}
                {(r.tokens_in != null && r.tokens_in > 0) ? ` · ${r.tokens_in}↑${r.tokens_out}↓ tok` : ""}
                {r.cost != null && r.cost > 0 ? ` · $${r.cost.toFixed(5)}` : ""}
              </span>
              <button
                className={`icon-btn lab-save-btn${isSaved ? " saved" : ""}`}
                title={isSaved ? lab.saved : lab.saveResult}
                disabled={isSaving}
                onClick={() => onSave(r)}
              >
                <Save size={13} />
              </button>
              <button className="icon-btn" title={lab.expand} onClick={() => onExpand(r)}>
                <Maximize2 size={13} />
              </button>
              <button className="icon-btn" title={lab.remove} onClick={() => onRemove(r.id)}>
                <X size={13} />
              </button>
            </div>
            {r.fields && Object.keys(r.fields).length > 0 && (
              <FieldChips
                fields={r.fields}
                onRemove={onFieldRemove ? (key) => onFieldRemove(r.id, key) : undefined}
              />
            )}
            <pre className="lab-card-text">{r.text || "—"}</pre>
          </div>
        );
      })}
    </div>
  );
}
