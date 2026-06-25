import { Sparkles, FileText, DollarSign } from "lucide-react";
import type { Document } from "../../types";
import { DocumentCard } from "../documents/DocumentCard";
import { useT } from "../../i18n";
import "./AIAnswer.css";

interface Props {
  answer: string;
  sources: Document[];
  cost: number;
  noProvider?: boolean;
  onDocClick: (idx: number) => void;
}

export function AIAnswer({ answer, sources, cost, noProvider, onDocClick }: Props) {
  const { t } = useT();

  if (noProvider) {
    return (
      <div className="ai-answer ai-answer--notice">
        <Sparkles size={20} className="ai-answer-notice-icon" />
        <span>{t.aiSearch.noProvider}</span>
      </div>
    );
  }

  if (!answer) {
    return (
      <div className="ai-answer ai-answer--notice">
        <span className="text-muted">{t.aiSearch.noAnswer}</span>
      </div>
    );
  }

  return (
    <div className="ai-answer">
      {/* Answer header */}
      <div className="ai-answer-header">
        <Sparkles size={15} className="ai-answer-header-icon" />
        <span className="ai-answer-header-label">{t.aiSearch.answer}</span>
        {cost > 0 && (
          <span className="ai-answer-cost">
            <DollarSign size={11} />
            {cost.toFixed(4)}
          </span>
        )}
      </div>

      {/* Answer body */}
      <div className="ai-answer-body">
        {answer.split("\n").filter(Boolean).map((line, i) => (
          <p key={i}>{line}</p>
        ))}
      </div>

      {/* Source documents */}
      {sources.length > 0 && (
        <div className="ai-sources">
          <div className="ai-sources-header">
            <FileText size={13} />
            <span>{t.aiSearch.sources}</span>
          </div>
          <div className="ai-sources-list">
            {sources.map((doc, i) => (
              <DocumentCard
                key={doc.id}
                doc={doc}
                mode="list"
                onClick={() => onDocClick(i)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
