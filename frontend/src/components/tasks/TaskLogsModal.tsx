import { useEffect, useRef, useState } from "react";
import { Modal } from "../ui/Modal";
import { useT } from "../../i18n";
import { getTaskLogs } from "../../api/documents";
import type { Task, TaskLog } from "../../types";

interface LogsModalProps {
  task: Task;
  t: ReturnType<typeof useT>["t"];
  onClose: () => void;
}

export function TaskLogsModal({ task, t, onClose }: LogsModalProps) {
  const [logs, setLogs] = useState<TaskLog[]>([]);
  const [loading, setLoading] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getTaskLogs(task.id)
      .then(setLogs)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [task.id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  useEffect(() => {
    if (task.status !== "running") return;
    const id = setInterval(() => {
      getTaskLogs(task.id).then(setLogs).catch(() => {});
    }, 2000);
    return () => clearInterval(id);
  }, [task.id, task.status]);

  return (
    <Modal open onClose={onClose} title={`${t.tasks.logsTitle} — ${task.title}`} size="lg">
      {!loading && logs.length > 0 && (
        <div className="logs-count-header text-xs text-muted">
          {t.tasks.logsLastN.replace("{{count}}", String(logs.length))}
        </div>
      )}
      <div className="logs-container">
        {loading ? (
          <div className="logs-empty text-muted">{t.loading}</div>
        ) : logs.length === 0 ? (
          <div className="logs-empty text-muted">{t.tasks.logsEmpty}</div>
        ) : (
          logs.map(log => (
            <div key={log.id} className={`log-line log-line--${log.level}`}>
              <span className="log-time text-xs text-muted">
                {log.created_at ? new Date(log.created_at + "Z").toLocaleTimeString() : ""}
              </span>
              <span className="log-message">{log.message}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </Modal>
  );
}
