import { useState } from "react";
import { Sparkles, FileText, DollarSign, Bug } from "lucide-react";
import type { Document, AskDebug } from "../../types";
import { DocumentCard } from "../documents/DocumentCard";
import { AskDebugModal } from "./AskDebugModal";
import { useT } from "../../i18n";
import "./AIAnswer.css";

interface Props {
  answer: string;
  sources: Document[];
  cost: number;
  noProvider?: boolean;
  onDocClick: (idx: number) => void;
  tokensIn?: number;
  tokensOut?: number;
  modelName?: string | null;
  docsSent?: number;
  devMode?: boolean;
  debug?: AskDebug | null;
  thumbVersions?: Record<number, number>;
}

export function AIAnswer({ answer, sources, cost, noProvider, onDocClick,
  tokensIn, tokensOut, modelName, docsSent, devMode, debug, thumbVersions }: Props) {
  const { t } = useT();
  const [showDebug, setShowDebug] = useState(false);

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

      {/* Dev info row — visible when devMode */}
      {devMode && (modelName || (tokensIn != null) || (docsSent != null) || debug) && (
        <div className="ai-answer-dev-row">
          {modelName && <span className="ai-dev-chip">{modelName}</span>}
          {(tokensIn != null || tokensOut != null) && (
            <span className="ai-dev-chip">
              {tokensIn ?? 0} {t.aiSearch.tokensIn} / {tokensOut ?? 0} {t.aiSearch.tokensOut}
            </span>
          )}
          {docsSent != null && (
            <span className="ai-dev-chip">{docsSent} {t.aiSearch.docsSent}</span>
          )}
          {debug && (
            <button type="button" className="ai-dev-log-btn" onClick={() => setShowDebug(true)}>
              <Bug size={12} />
              {t.aiSearch.debug.open}
            </button>
          )}
        </div>
      )}

      {showDebug && debug && (
        <AskDebugModal debug={debug} onClose={() => setShowDebug(false)} />
      )}

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
                thumbVersion={thumbVersions?.[doc.id]}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
