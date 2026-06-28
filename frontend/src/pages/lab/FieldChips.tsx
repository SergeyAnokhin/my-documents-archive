import { X } from "lucide-react";
import type { ExtractedFields } from "../../types";

/** Compact chips summarising the structured fields extracted from a result. */
export function FieldChips({
  fields,
  onRemove,
}: {
  fields: ExtractedFields;
  onRemove?: (key: string) => void;
}) {
  const chips: { key: string; value: string }[] = [];
  if (fields.document_type) chips.push({ key: "type", value: fields.document_type.replace(/_/g, " ") });
  if (fields.document_date) chips.push({ key: "date", value: fields.document_date });
  const name = [fields.person_first_name, fields.person_last_name].filter(Boolean).join(" ");
  if (name) chips.push({ key: "person", value: name });
  if (fields.organization) chips.push({ key: "org", value: fields.organization });
  if (fields.amount != null) {
    const amt = fields.amount_currency ? `${fields.amount} ${fields.amount_currency}` : String(fields.amount);
    chips.push({ key: "amount", value: amt });
  }
  if (fields.language) chips.push({ key: "lang", value: fields.language });
  if (chips.length === 0) return null;
  return (
    <div className="lab-field-chips">
      {chips.map(c => (
        <span key={c.key} className={`lab-field-chip lab-field-chip--${c.key}`} title={c.key}>
          {c.value}
          {onRemove && (
            <button
              className="lab-field-chip-remove"
              onClick={() => onRemove(c.key)}
              title="Remove"
            >
              <X size={9} />
            </button>
          )}
        </span>
      ))}
    </div>
  );
}
