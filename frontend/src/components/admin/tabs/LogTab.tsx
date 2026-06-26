import { useState, useEffect } from "react";
import { useT } from "../../../i18n";
import { getLog } from "../../../api/documents";
import type { LogEntry } from "../../../types";

export function LogTab() {
  const { t } = useT();
  const [log, setLog] = useState<LogEntry[]>([]);

  useEffect(() => {
    getLog(50).then(setLog).catch(() => {});
  }, []);

  if (log.length === 0) return <p className="text-muted">{t.admin.log.empty}</p>;

  return (
    <div className="log-list">
      {log.map((entry) => (
        <div key={entry.id} className="log-row">
          <span className={`status-dot ${entry.status === "done" ? "done" : entry.status === "error" ? "error" : "pending"}`} />
          <span className="text-xs text-muted log-time">
            {entry.created_at ? new Date(entry.created_at).toLocaleTimeString() : ""}
          </span>
          <span className="log-step text-xs">{entry.step}</span>
          <span className="text-sm truncate">{entry.message}</span>
        </div>
      ))}
    </div>
  );
}
