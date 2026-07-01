import { useEffect, useState } from "react";
import { Check, Loader2 } from "lucide-react";
import { AIAnswer } from "../../components/search/AIAnswer";
import { useT } from "../../i18n";
import type { AIAnswerResponse } from "../../types";

interface Props {
  t: ReturnType<typeof useT>["t"];
  aiLoading: boolean;
  aiAnswer: AIAnswerResponse | null;
  devMode: boolean;
  thumbVersions: Record<number, number>;
  onDocClick: (index: number) => void;
}

export function HomePageAIMode({ t, aiLoading, aiAnswer, devMode, thumbVersions, onDocClick }: Props) {
  return (
    <div className="ai-mode-content">
      {aiLoading && <AISearchProgress t={t} />}
      {!aiLoading && aiAnswer && (
        <AIAnswer
          answer={aiAnswer.answer}
          sources={aiAnswer.sources}
          sourceSimilarities={aiAnswer.source_similarities}
          cost={aiAnswer.cost}
          noProvider={aiAnswer.no_provider}
          onDocClick={onDocClick}
          tokensIn={aiAnswer.tokens_in}
          tokensOut={aiAnswer.tokens_out}
          modelName={aiAnswer.model_name}
          docsSent={aiAnswer.docs_sent}
          devMode={devMode}
          debug={aiAnswer.debug}
          thumbVersions={thumbVersions}
        />
      )}
      {!aiLoading && !aiAnswer && (
        <AskHint t={t} />
      )}
    </div>
  );
}

const _STEP_DELAYS = [0, 320, 680, 1050]; // ms when each step becomes active

function AISearchProgress({ t }: { t: ReturnType<typeof useT>["t"] }) {
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    const timers = _STEP_DELAYS.slice(1).map((ms, i) =>
      window.setTimeout(() => setActiveIdx(i + 1), ms)
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  const steps = [
    t.aiSearch.stepText,
    t.aiSearch.stepSemantic,
    t.aiSearch.stepRank,
    t.aiSearch.stepLlm,
  ];

  return (
    <div className="ai-search-progress">
      {steps.map((label, i) => {
        const done   = i < activeIdx;
        const active = i === activeIdx;
        return (
          <div key={i} className={`ai-progress-step${done ? " done" : active ? " active" : ""}`}>
            <span className="ai-step-icon">
              {done   ? <Check size={13} />
               : active ? <Loader2 size={13} className="ai-step-spin" />
               : null}
            </span>
            <span>{label}</span>
          </div>
        );
      })}
    </div>
  );
}

function AskHint({ t }: { t: ReturnType<typeof useT>["t"] }) {
  return (
    <div className="ask-hint">
      <div className="ask-hint-icon">✨</div>
      <p className="ask-hint-text text-muted">{t.aiSearch.placeholder}</p>
    </div>
  );
}
