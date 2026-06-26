import { Save, X } from "lucide-react";
import { useT } from "../../i18n";
import type { LabResult } from "../../types";
import { formatMs } from "./labUtils";
import { FieldChips } from "./FieldChips";

/** Draggable floating modal showing one result's full text. */
export function FloatingTextModal({
  result,
  pos,
  savingId,
  savedId,
  onDragStart,
  onSave,
  onClose,
}: {
  result: LabResult;
  pos: { x: number; y: number };
  savingId: string | null;
  savedId: string | null;
  onDragStart: (e: React.MouseEvent, curPos: { x: number; y: number }) => void;
  onSave: (r: LabResult) => void;
  onClose: () => void;
}) {
  const { t } = useT();
  const lab = t.lab;
  const isSaving = savingId === result.id;
  const isSaved = savedId === result.id;

  return (
    <div className="lab-float-modal" style={{ left: pos.x, top: pos.y }}>
      <div className="lab-float-header" onMouseDown={e => onDragStart(e, pos)}>
        <span className={`lab-kind ${result.kind}`}>
          {result.kind === "ocr" ? "OCR" : "AI"}
        </span>
        <span className="lab-float-label">{result.label}</span>
        <span className="lab-float-time text-muted">{formatMs(result.ms)}</span>
        <button
          className={`icon-btn lab-save-btn${isSaved ? " saved" : ""}`}
          title={isSaved ? lab.saved : lab.saveResult}
          disabled={isSaving}
          onClick={() => onSave(result)}
        >
          <Save size={13} />
        </button>
        <button className="icon-btn" onClick={onClose} title={lab.remove}>
          <X size={13} />
        </button>
      </div>
      {result.fields && Object.keys(result.fields).length > 0 && (
        <div className="lab-float-fields">
          <FieldChips fields={result.fields} />
        </div>
      )}
      <pre className="lab-float-text">{result.text || "—"}</pre>
    </div>
  );
}
