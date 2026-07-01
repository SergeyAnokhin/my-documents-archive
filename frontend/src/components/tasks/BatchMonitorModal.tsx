import { useState } from "react";
import { Square, Play, ScrollText, Download } from "lucide-react";
import { Modal } from "../ui/Modal";
import { useT } from "../../i18n";
import { runTask, stopTask, resumeBatchTask, getBatchResultUrl } from "../../api/documents";
import type { Task, TaskType } from "../../types";
import { TASK_LABELS, BATCH_CONSOLE_URLS, BATCH_TASK_TYPES } from "./taskConfig";

interface BatchMonitorProps {
  tasks: Task[];
  t: ReturnType<typeof useT>["t"];
  onRefresh: () => Promise<void>;
  onLogs: (task: Task) => void;
  onClose: () => void;
}

export function BatchMonitorModal({ tasks, t, onRefresh, onLogs, onClose }: BatchMonitorProps) {
  const batchTasks = tasks.filter(tk => BATCH_TASK_TYPES.includes(tk.task_type));
  const [resuming, setResuming] = useState<number | null>(null);

  // Sort: running → stopped/error → done → idle
  const sorted = [...batchTasks].sort((a, b) => {
    const order: Record<string, number> = { running: 0, stopped: 1, error: 2, done: 3, idle: 4 };
    return (order[a.status] ?? 5) - (order[b.status] ?? 5);
  });

  const handleResume = async (task: Task) => {
    setResuming(task.id);
    try {
      await resumeBatchTask(task.id);
      await onRefresh();
    } catch { /* ignore */ } finally {
      setResuming(null);
    }
  };

  const handleRun = async (task: Task) => {
    await runTask(task.id);
    await onRefresh();
  };

  const handleStop = async (task: Task) => {
    await stopTask(task.id);
    await onRefresh();
  };

  const statusLabel: Record<string, string> = {
    idle:    t.tasks.statusIdle,
    running: t.tasks.statusRunning,
    done:    t.tasks.statusDone,
    error:   t.tasks.statusError,
    stopped: t.tasks.statusStopped,
  };

  return (
    <Modal open onClose={onClose} title={t.tasks.batchMonitorTitle} size="lg">
      <p className="batch-monitor-hint text-sm text-muted">{t.tasks.batchMonitorHint}</p>

      {sorted.length === 0 ? (
        <div className="batch-monitor-empty text-muted text-sm">{t.tasks.batchMonitorEmpty}</div>
      ) : (
        <div className="batch-monitor-list">
          {sorted.map(task => {
            const taskType = task.task_type as TaskType;
            const jobId = task.result_summary?.batch_job_id as string | undefined;
            const docCount = task.result_summary?.doc_count as number | undefined;
            const hasJobId = !!jobId;
            const canResume = hasJobId && task.status !== "running";
            const progressPct = task.progress_total > 0
              ? Math.round((task.progress_current / task.progress_total) * 100)
              : 0;
            const resultEntries = task.result_summary
              ? Object.entries(task.result_summary).filter(([k]) => k !== "batch_job_id" && k !== "phase" && k !== "doc_count")
              : [];

            return (
              <div key={task.id} className={`batch-monitor-row batch-monitor-row--${task.status}`}>
                <div className="batch-monitor-row-header">
                  <span className="task-type-label">{TASK_LABELS[taskType] ?? taskType}</span>
                  <span className="batch-monitor-row-title">{task.title}</span>
                  <span className={`task-badge task-badge--${task.status}`}>
                    {statusLabel[task.status] ?? task.status}
                  </span>
                </div>

                {/* Job ID */}
                {hasJobId ? (
                  <div className="batch-monitor-jobid">
                    <span className="text-xs text-muted">{t.tasks.batchJobId}:</span>
                    <code className="batch-monitor-jobid-value">{String(jobId)}</code>
                    {docCount !== undefined && (
                      <span className="text-xs text-muted">
                        · {t.tasks.batchDocCount.replace("{{count}}", String(docCount))}
                      </span>
                    )}
                    {BATCH_CONSOLE_URLS[taskType] && (
                      <a
                        className="task-console-link"
                        href={BATCH_CONSOLE_URLS[taskType]}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        Console ↗
                      </a>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-muted">{t.tasks.batchNoJobId}</p>
                )}

                {/* Progress bar */}
                {task.progress_total > 0 && task.status === "running" && (
                  <div className="task-progress-wrap">
                    <div className="task-progress-bar">
                      <div className="task-progress-fill" style={{ width: `${progressPct}%` }} />
                    </div>
                    <span className="task-progress-label text-xs text-muted">
                      {t.tasks.progress
                        .replace("{{current}}", String(task.progress_current))
                        .replace("{{total}}", String(task.progress_total))}
                    </span>
                  </div>
                )}

                {/* Result summary */}
                {resultEntries.length > 0 && (
                  <div className="task-result">
                    {resultEntries.map(([k, v]) => (
                      <span key={k} className="task-result-item text-xs text-muted">
                        <span className="task-result-key">{k}</span>
                        <span>{String(v)}</span>
                      </span>
                    ))}
                  </div>
                )}

                {/* Resume hint for stopped tasks */}
                {canResume && task.status === "stopped" && (
                  <p className="text-xs text-muted batch-monitor-resume-hint">
                    {t.tasks.batchResumeHint}
                  </p>
                )}

                {/* Actions */}
                <div className="batch-monitor-row-actions">
                  <button className="task-btn-ghost" onClick={() => onLogs(task)} title={t.tasks.logs}>
                    <ScrollText size={14} />
                    <span>{t.tasks.logs}</span>
                  </button>
                  {task.status === "done" && (
                    <a
                      className="task-btn-ghost"
                      href={getBatchResultUrl(task.id)}
                      download={`batch_result_task_${task.id}.jsonl`}
                      title={t.tasks.batchDownloadResult}
                    >
                      <Download size={14} />
                      <span>{t.tasks.batchDownloadResult}</span>
                    </a>
                  )}
                  <div className="task-card-actions">
                    {task.status === "running" ? (
                      <button className="task-btn task-btn--stop" onClick={() => handleStop(task)}>
                        <Square size={13} />
                        <span>{t.tasks.stop}</span>
                      </button>
                    ) : task.status !== "done" && (canResume ? (
                      <button
                        className="task-btn task-btn--run"
                        onClick={() => handleResume(task)}
                        disabled={resuming === task.id}
                        title={t.tasks.batchResumeHint}
                      >
                        <Play size={13} />
                        <span>{resuming === task.id ? "…" : t.tasks.batchResume}</span>
                      </button>
                    ) : (
                      <button className="task-btn task-btn--run" onClick={() => handleRun(task)}>
                        <Play size={13} />
                        <span>{task.status === "stopped" ? t.tasks.resume : t.tasks.run}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
