import { useState } from "react";
import { Sparkles, FileText, DollarSign, Bug } from "lucide-react";
import type { Document, AskDebug } from "../../types";
import { DocumentCard } from "../documents/DocumentCard";
import { AskDebugModal } from "./AskDebugModal";
import { useT } from "../../i18n";
import "./AIAnswer.css";

// ── Minimal markdown renderer ────────────────────────────────────────────────

function renderInline(text: string, onCite: (i: number) => void): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|\[\d+\])/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    const citeMatch = part.match(/^\[(\d+)\]$/);
    if (citeMatch) {
      const n = parseInt(citeMatch[1]);
      return (
        <button key={i} className="ai-cite-ref" onClick={() => onCite(n - 1)} title={`Source ${n}`}>
          {n}
        </button>
      );
    }
    return part || null;
  });
}

function renderMarkdown(answer: string, onCite: (i: number) => void): React.ReactNode[] {
  const lines = answer.split("\n");
  const nodes: React.ReactNode[] = [];
  let listItems: React.ReactNode[] = [];
  let listType: "ol" | "ul" | null = null;

  function flushList() {
    if (listItems.length === 0) return;
    const key = `list-${nodes.length}`;
    nodes.push(listType === "ol"
      ? <ol key={key}>{listItems}</ol>
      : <ul key={key}>{listItems}</ul>,
    );
    listItems = [];
    listType = null;
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) { flushList(); continue; }

    const numMatch = trimmed.match(/^(\d+)\.\s+(.+)$/);
    const bulletMatch = trimmed.match(/^[-*]\s+(.+)$/);

    if (numMatch) {
      if (listType === "ul") flushList();
      listType = "ol";
      listItems.push(<li key={listItems.length}>{renderInline(numMatch[2], onCite)}</li>);
    } else if (bulletMatch) {
      if (listType === "ol") flushList();
      listType = "ul";
      listItems.push(<li key={listItems.length}>{renderInline(bulletMatch[1], onCite)}</li>);
    } else {
      flushList();
      nodes.push(<p key={`p-${nodes.length}`}>{renderInline(trimmed, onCite)}</p>);
    }
  }
  flushList();
  return nodes;
}

interface Props {
  answer: string;
  sources: Document[];
  sourceSimilarities?: (number | null)[];
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

export function AIAnswer({ answer, sources, sourceSimilarities, cost, noProvider, onDocClick,
  tokensIn, tokensOut, modelName, docsSent, devMode, debug, thumbVersions }: Props) {
  const { t } = useT();
  const [showDebug, setShowDebug] = useState(false);

  const scrollToSource = (idx: number) => {
    document.getElementById(`ai-source-${idx}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

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
        {renderMarkdown(answer, scrollToSource)}
      </div>

      {/* Source documents */}
      {sources.length > 0 && (
        <div className="ai-sources">
          <div className="ai-sources-header">
            <FileText size={13} />
            <span>{t.aiSearch.sources}</span>
          </div>
          <div className="ai-sources-list">
            {sources.map((doc, i) => {
              const sim = sourceSimilarities?.[i];
              return (
                <div key={doc.id} id={`ai-source-${i}`}>
                  <DocumentCard
                    doc={doc}
                    mode="list"
                    onClick={() => onDocClick(i)}
                    thumbVersion={thumbVersions?.[doc.id]}
                    score={sim != null && sim > 0 ? sim : undefined}
                  />
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
