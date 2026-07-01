import { Square, Play, ScrollText, Trash2, GripVertical, Clock } from "lucide-react";
import { useT } from "../../i18n";
import type { Task, TaskType } from "../../types";
import { TASK_LABELS, BATCH_CONSOLE_URLS, formatDuration } from "./taskConfig";

interface CardProps {
  task: Task;
  t: ReturnType<typeof useT>["t"];
  now: number;
  isDragging: boolean;
  isDragOver: boolean;
  isStarting: boolean;
  onRun: () => void;
  onStop: () => void;
  onDelete: () => void;
  onLogs: () => void;
  onDragStart: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onDragEnd: () => void;
}

export function TaskCard({
  task, t, now, isDragging, isDragOver, isStarting,
  onRun, onStop, onDelete, onLogs,
  onDragStart, onDragOver, onDrop, onDragEnd,
}: CardProps) {
  const taskType = task.task_type as TaskType;
  const progressPct = task.progress_total > 0
    ? Math.round((task.progress_current / task.progress_total) * 100)
    : 0;

  const statusLabel: Record<string, string> = {
    idle:    t.tasks.statusIdle,
    running: t.tasks.statusRunning,
    done:    t.tasks.statusDone,
    error:   t.tasks.statusError,
    stopped: t.tasks.statusStopped,
  };

  const resultEntries = task.result_summary
    ? Object.entries(task.result_summary).filter(([k]) => k !== "batch_job_id" && k !== "phase")
    : [];

  const elapsedMs = (() => {
    if (!task.started_at) return null;
    const start = new Date(task.started_at + "Z").getTime();
    if (task.status === "running") return now - start;
    if (task.finished_at) return new Date(task.finished_at + "Z").getTime() - start;
    return null;
  })();

  const dur = t.tasks;
  const durationStr = elapsedMs !== null
    ? formatDuration(elapsedMs, dur.durationHour, dur.durationMin, dur.durationSec)
    : null;

  return (
    <div
      className={[
        "task-card",
        `task-card--${task.status}`,
        isDragging  ? "task-card--dragging"  : "",
        isDragOver  ? "task-card--drag-over" : "",
      ].join(" ")}
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
    >
      {/* Header */}
      <div className="task-card-header">
        <span className="task-card-drag" title="Drag to reorder">
          <GripVertical size={15} />
        </span>
        <span className="task-type-label">
          {TASK_LABELS[taskType] ?? taskType}
        </span>
        <span className="task-card-title">{task.title}</span>
        <span className={`task-badge task-badge--${task.status}`}>
          {statusLabel[task.status] ?? task.status}
        </span>
      </div>

      {/* Description */}
      <p className="task-card-desc">
        {t.tasks.descriptions[taskType as keyof typeof t.tasks.descriptions] ?? ""}
        {!!task.config?.quality_filter && (
          <span className="task-quality-badge">
            {String(task.config.quality_filter as string).replace(/_/g, " ")}
          </span>
        )}
      </p>

      {/* Progress bar — shown while running or after finish if total > 0 */}
      {task.progress_total > 0 && (task.status === "running" || task.status === "done") && (
        <div className="task-progress-wrap">
          <div className="task-progress-bar">
            <div
              className="task-progress-fill"
              style={{ width: `${task.status === "done" ? 100 : progressPct}%` }}
            />
          </div>
          <span className="task-progress-label text-xs text-muted">
            {t.tasks.progress
              .replace("{{current}}", String(task.progress_current))
              .replace("{{total}}", String(task.progress_total))}
          </span>
        </div>
      )}

      {/* Result summary (skip internal phase/job_id fields) */}
      {task.status === "done" && (resultEntries.length > 0 || durationStr !== null) && (
        <div className="task-result">
          {resultEntries.map(([k, v]) => (
            <span key={k} className="task-result-item text-xs text-muted">
              <span className="task-result-key">{k}</span>
              <span>{String(v)}</span>
            </span>
          ))}
          {durationStr !== null && (
            <span className="task-result-item text-xs text-muted">
              <span className="task-result-key">{t.tasks.durationLabel}</span>
              <span>{durationStr}</span>
            </span>
          )}
        </div>
      )}

      {/* Batch job ID + console link — shown while running */}
      {task.status === "running" && !!task.result_summary?.batch_job_id && (
        <div className="task-batch-meta">
          <span className="task-batch-jobid text-xs text-muted">
            job: {String(task.result_summary.batch_job_id)}
          </span>
          {BATCH_CONSOLE_URLS[taskType] && (
            <a
              className="task-console-link"
              href={BATCH_CONSOLE_URLS[taskType]}
              target="_blank"
              rel="noopener noreferrer"
            >
              Batches ↗
            </a>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="task-card-footer">
        <div className="task-footer-left">
          <button className="task-btn-ghost" onClick={onLogs} title={t.tasks.logs}>
            <ScrollText size={14} />
            <span>{t.tasks.logs}</span>
          </button>
          {task.status === "running" && durationStr !== null && (
            <span className="task-timing">
              <Clock size={11} />
              {durationStr}
            </span>
          )}
        </div>
        <div className="task-card-actions">
          <button className="task-btn-ghost task-btn-danger" onClick={onDelete} title={t.tasks.deleteTask}>
            <Trash2 size={14} />
          </button>
          {task.status === "running" ? (
            <button className="task-btn task-btn--stop" onClick={onStop}>
              <Square size={13} />
              <span>{t.tasks.stop}</span>
            </button>
          ) : task.status !== "done" && (
            <button className="task-btn task-btn--run" onClick={onRun} disabled={isStarting}>
              {isStarting ? <span className="task-btn-spinner" /> : <Play size={13} />}
              <span>{isStarting ? "…" : task.status === "stopped" ? t.tasks.resume : t.tasks.run}</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
