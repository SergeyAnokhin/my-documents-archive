import { useState, useEffect, useCallback } from "react";
import { useT } from "../../../i18n";
import { getLog } from "../../../api/documents";
import type { LogEntry } from "../../../types";

const LEVELS = ["trace", "debug", "info", "warning", "error"] as const;
type Level = typeof LEVELS[number];

const LEVEL_COLORS: Record<Level, string> = {
  trace:   "var(--text-disabled, #555)",
  debug:   "var(--text-muted, #888)",
  info:    "var(--color-primary, #4a9eff)",
  warning: "#f5a623",
  error:   "var(--color-danger, #e05c5c)",
};

export function LogTab() {
  const { t } = useT();
  const [log, setLog] = useState<LogEntry[]>([]);
  const [minLevel, setMinLevel] = useState<Level>("info");

  const load = useCallback((level: Level) => {
    getLog(100, level).then(setLog).catch(() => {});
  }, []);

  useEffect(() => { load(minLevel); }, [minLevel, load]);

  return (
    <div>
      <div className="log-level-bar">
        <span className="text-xs text-muted" style={{ marginRight: 8 }}>
          {t.admin.log.levelFilter}:
        </span>
        {LEVELS.map((lvl) => (
          <button
            key={lvl}
            className={`log-level-pill${minLevel === lvl ? " active" : ""}`}
            style={minLevel === lvl ? { borderColor: LEVEL_COLORS[lvl], color: LEVEL_COLORS[lvl] } : {}}
            onClick={() => setMinLevel(lvl)}
          >
            {t.admin.log.levels[lvl]}
          </button>
        ))}
      </div>

      {log.length === 0 ? (
        <p className="text-muted">{t.admin.log.empty}</p>
      ) : (
        <div className="log-list">
          {log.map((entry) => {
            const lvl = (entry.level ?? "info") as Level;
            return (
              <div key={entry.id} className="log-row">
                <span
                  className={`status-dot ${entry.status === "done" ? "done" : entry.status === "error" ? "error" : "pending"}`}
                />
                <span className="text-xs text-muted log-time">
                  {entry.created_at ? new Date(entry.created_at).toLocaleTimeString() : ""}
                </span>
                <span
                  className="log-level-badge text-xs"
                  style={{ color: LEVEL_COLORS[lvl] }}
                >
                  {t.admin.log.levels[lvl] ?? lvl}
                </span>
                <span className="log-step text-xs">{entry.step}</span>
                <span className="text-sm truncate">{entry.message}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
