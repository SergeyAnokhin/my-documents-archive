import { Scale, Trophy, Save } from "lucide-react";
import { Button } from "../../components/ui/Button";
import { useT } from "../../i18n";
import type { AIProvider, LabJudgeResult } from "../../types";
import { formatMs } from "./labUtils";
import { FieldChips } from "./FieldChips";

/** Premium "judge" section: pick providers, compare candidates, show verdicts. */
export function JudgePanel({
  premiumProviders,
  judgeProviders,
  setJudgeProviders,
  judgingIds,
  judgeResults,
  judgeErrors,
  resultsCount,
  savingId,
  savedId,
  onJudge,
  onSaveJudge,
}: {
  premiumProviders: AIProvider[];
  judgeProviders: number[];
  setJudgeProviders: React.Dispatch<React.SetStateAction<number[]>>;
  judgingIds: number[];
  judgeResults: Record<number, LabJudgeResult>;
  judgeErrors: Record<number, string>;
  resultsCount: number;
  savingId: string | null;
  savedId: string | null;
  onJudge: () => void;
  onSaveJudge: (providerId: number, providerName: string, result: LabJudgeResult) => void;
}) {
  const { t } = useT();
  const lab = t.lab;

  if (premiumProviders.length === 0) {
    return <p className="text-xs text-muted">{lab.noPremium}</p>;
  }

  return (
    <>
      <p className="text-xs text-muted" style={{ marginBottom: 8 }}>{lab.judgeHint}</p>
      <div className="lab-judge-list">
        {premiumProviders.map(p => {
          const hasVision = p.capabilities?.vision ?? false;
          const isChecked = judgeProviders.includes(p.id);
          const isRunning = judgingIds.includes(p.id);
          return (
            <label key={p.id} className="lab-judge-item">
              <input
                type="checkbox"
                checked={isChecked}
                onChange={e => setJudgeProviders(prev =>
                  e.target.checked ? [...prev, p.id] : prev.filter(id => id !== p.id),
                )}
              />
              <span className={`lab-capability-badge ${hasVision ? "vision" : "text"}`}>
                {hasVision ? t.admin.ai.visionBadge : lab.textBadge}
              </span>
              <span className="lab-judge-name">{p.name}</span>
              {isRunning && <span className="lab-judge-running">…</span>}
            </label>
          );
        })}
      </div>

      <Button
        variant="primary" size="sm"
        icon={<Scale size={14} />}
        loading={judgingIds.length > 0}
        disabled={resultsCount < 2 || judgeProviders.length === 0}
        onClick={onJudge}
        style={{ marginTop: 8 }}
      >
        {judgingIds.length > 0 ? lab.comparing : lab.compare}
      </Button>
      {resultsCount < 2 && <p className="text-xs text-muted" style={{ marginTop: 6 }}>{lab.needTwo}</p>}

      {premiumProviders
        .filter(p => judgeResults[p.id] || judgeErrors[p.id])
        .map(p => {
          const result = judgeResults[p.id];
          const error = judgeErrors[p.id];
          const hasVision = p.capabilities?.vision ?? false;
          return (
            <div key={p.id}>
              <div className="lab-verdict-judge-header">
                <span className={`lab-capability-badge ${hasVision ? "vision" : "text"}`}>
                  {hasVision ? t.admin.ai.visionBadge : lab.textBadge}
                </span>
                <span>{p.name}</span>
              </div>
              {error && (
                <p className="text-xs" style={{ color: "var(--color-error)", marginTop: 4 }}>{error}</p>
              )}
              {result && (
                <div className="lab-verdict">
                  <div className="lab-verdict-best">
                    <Trophy size={15} /> {lab.best}: <strong>{result.best}</strong>
                  </div>
                  {result.summary && <p className="lab-verdict-summary">{result.summary}</p>}
                  <ul className="lab-verdict-list">
                    {result.rankings.map((rk, i) => (
                      <li key={i} className="lab-verdict-item">
                        <span className="lab-verdict-score">{rk.score}</span>
                        <span className="lab-verdict-label">{rk.label}</span>
                        <span className="lab-verdict-comment text-muted">{rk.comment}</span>
                      </li>
                    ))}
                  </ul>
                  {result.fields && Object.keys(result.fields).length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      <p className="text-xs text-muted" style={{ marginBottom: 4 }}>{lab.judgeFields}</p>
                      <FieldChips fields={result.fields} />
                    </div>
                  )}
                  {(result.corrected || result.fields) && (
                    <div style={{ marginTop: 10 }}>
                      {result.corrected && (
                        <>
                          <p className="text-xs text-muted" style={{ marginBottom: 4 }}>{lab.corrected}</p>
                          <pre className="lab-card-text" style={{ height: 120 }}>{result.corrected}</pre>
                        </>
                      )}
                      <div style={{ marginTop: 6 }}>
                        {(() => {
                          const fakeId = `judge-${p.id}`;
                          const isSaving = savingId === fakeId;
                          const isSaved = savedId === fakeId;
                          return (
                            <button
                              className={`lab-save-btn-inline${isSaved ? " saved" : ""}`}
                              title={isSaved ? lab.saved : lab.saveResult}
                              disabled={isSaving || (!result.corrected && !result.fields)}
                              onClick={() => onSaveJudge(p.id, p.name, result)}
                            >
                              <Save size={12} />
                              {isSaved ? lab.saved : isSaving ? lab.saving : lab.saveResult}
                            </button>
                          );
                        })()}
                      </div>
                    </div>
                  )}
                  <p className="text-xs text-muted" style={{ marginTop: 6 }}>
                    {formatMs(result.ms)}
                    {result.tokens_in ? ` · ${result.tokens_in}↑${result.tokens_out}↓ tok` : ""}
                    {result.cost > 0 ? ` · $${result.cost.toFixed(5)}` : ""}
                  </p>
                </div>
              )}
            </div>
          );
        })}
    </>
  );
}
