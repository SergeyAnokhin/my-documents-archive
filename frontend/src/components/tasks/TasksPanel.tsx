import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, Square, Play, ScrollText, Trash2, X, GripVertical, ChevronLeft } from "lucide-react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";
import {
  listTasks, createTask, deleteTask, runTask, stopTask,
  stopAllTasks, getTaskLogs, updateTask, listProviders, getTaskCandidates,
} from "../../api/documents";
import type { AIProvider, Task, TaskLog, TaskType } from "../../types";
import "./TasksPanel.css";

// ── Task type short labels ────────────────────────────────────────────────────

const TASK_LABELS: Record<TaskType, string> = {
  index_unindexed:         "OCR",
  sync_library:            "SYNC",
  reclassify_unclassified: "CLASSIFY",
  reclassify_all:          "RECLASSIFY",
  batch_ocr_mistral:       "BATCH OCR",
  batch_ocr_gemini:        "BATCH OCR",
  cleanup_missing:         "CLEANUP",
};

const ALL_TYPES: TaskType[] = [
  "index_unindexed",
  "sync_library",
  "reclassify_unclassified",
  "reclassify_all",
  "batch_ocr_mistral",
  "batch_ocr_gemini",
  "cleanup_missing",
];

const TYPES_WITH_LIMIT: TaskType[] = [
  "index_unindexed",
  "reclassify_unclassified",
  "reclassify_all",
  "batch_ocr_mistral",
  "batch_ocr_gemini",
];

// Batch tasks that pick an async provider + poll interval, mapped to the
// provider_type they require.
const BATCH_PROVIDER_TYPE: Partial<Record<TaskType, string>> = {
  batch_ocr_mistral: "mistral",
  batch_ocr_gemini:  "gemini",
};

// External documentation links for task types that have official provider docs.
const TASK_DOC_URLS: Partial<Record<TaskType, string>> = {
  batch_ocr_mistral: "https://docs.mistral.ai/capabilities/batch/",
  batch_ocr_gemini:  "https://ai.google.dev/gemini-api/docs/batch-mode",
};

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean;
  onClose: () => void;
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function TasksPanel({ open, onClose }: Props) {
  const { t } = useT();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [logsTask, setLogsTask] = useState<Task | null>(null);
  const [draggedId, setDraggedId] = useState<number | null>(null);
  const [dragOverId, setDragOverId] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await listTasks();
      setTasks(data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    load().finally(() => setLoading(false));
  }, [open, load]);

  // Poll while any task is running
  useEffect(() => {
    const hasRunning = tasks.some(tk => tk.status === "running");
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(load, 3000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, [tasks, load]);

  const handleRun = async (task: Task) => {
    await runTask(task.id);
    await load();
  };

  const handleStop = async (task: Task) => {
    await stopTask(task.id);
    await load();
  };

  const handleStopAll = async () => {
    await stopAllTasks();
    await load();
  };

  const handleDelete = async (task: Task) => {
    await deleteTask(task.id);
    setTasks(prev => prev.filter(tk => tk.id !== task.id));
  };

  const handleCreated = (task: Task) => {
    setTasks(prev => [...prev, task]);
    setShowCreate(false);
  };

  // ── Drag-and-drop reorder ──────────────────────────────────────────────────

  const handleDragStart = (id: number) => setDraggedId(id);
  const handleDragOver = (e: React.DragEvent, id: number) => {
    e.preventDefault();
    setDragOverId(id);
  };

  const handleDrop = async (e: React.DragEvent, targetId: number) => {
    e.preventDefault();
    if (draggedId === null || draggedId === targetId) {
      setDraggedId(null); setDragOverId(null); return;
    }
    const reordered = [...tasks];
    const fromIdx = reordered.findIndex(tk => tk.id === draggedId);
    const toIdx   = reordered.findIndex(tk => tk.id === targetId);
    const [moved] = reordered.splice(fromIdx, 1);
    reordered.splice(toIdx, 0, moved);
    const updated = reordered.map((tk, i) => ({ ...tk, sort_order: i }));
    setTasks(updated);
    setDraggedId(null);
    setDragOverId(null);
    for (const tk of updated) {
      updateTask(tk.id, { sort_order: tk.sort_order }).catch(() => {});
    }
  };

  const handleDragEnd = () => { setDraggedId(null); setDragOverId(null); };

  const anyRunning = tasks.some(tk => tk.status === "running");

  return (
    <>
      <Modal open={open} onClose={onClose} title={t.tasks.title} size="xl">
        <div className="tasks-toolbar">
          <div className="tasks-toolbar-left">
            {anyRunning && (
              <Button variant="danger" size="sm" icon={<Square size={13} />} onClick={handleStopAll}>
                {t.tasks.stopAll}
              </Button>
            )}
          </div>
          <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setShowCreate(true)}>
            {t.tasks.addTask}
          </Button>
        </div>

        {loading ? (
          <div className="tasks-loading">
            {[1, 2, 3].map(i => <div key={i} className="skeleton task-card-skeleton" />)}
          </div>
        ) : tasks.length === 0 ? (
          <TasksEmpty t={t} onAdd={() => setShowCreate(true)} />
        ) : (
          <div className="tasks-grid">
            {tasks.map(task => (
              <TaskCard
                key={task.id}
                task={task}
                t={t}
                isDragging={draggedId === task.id}
                isDragOver={dragOverId === task.id}
                onRun={() => handleRun(task)}
                onStop={() => handleStop(task)}
                onDelete={() => handleDelete(task)}
                onLogs={() => setLogsTask(task)}
                onDragStart={() => handleDragStart(task.id)}
                onDragOver={(e) => handleDragOver(e, task.id)}
                onDrop={(e) => handleDrop(e, task.id)}
                onDragEnd={handleDragEnd}
              />
            ))}
          </div>
        )}
      </Modal>

      {showCreate && (
        <CreateTaskModal
          t={t}
          onCreated={handleCreated}
          onClose={() => setShowCreate(false)}
        />
      )}

      {logsTask && (
        <TaskLogsModal
          task={logsTask}
          t={t}
          onClose={() => setLogsTask(null)}
        />
      )}
    </>
  );
}

// ── Task card ─────────────────────────────────────────────────────────────────

interface CardProps {
  task: Task;
  t: ReturnType<typeof useT>["t"];
  isDragging: boolean;
  isDragOver: boolean;
  onRun: () => void;
  onStop: () => void;
  onDelete: () => void;
  onLogs: () => void;
  onDragStart: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onDragEnd: () => void;
}

function TaskCard({
  task, t, isDragging, isDragOver,
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
      {task.status === "done" && resultEntries.length > 0 && (
        <div className="task-result">
          {resultEntries.map(([k, v]) => (
            <span key={k} className="task-result-item text-xs text-muted">
              <span className="task-result-key">{k}</span>
              <span>{String(v)}</span>
            </span>
          ))}
        </div>
      )}

      {/* Batch job ID — useful when polling */}
      {task.status === "running" && !!task.result_summary?.batch_job_id && (
        <p className="text-xs text-muted" style={{ fontFamily: "var(--font-mono)" }}>
          job: {String(task.result_summary.batch_job_id)}
        </p>
      )}

      {/* Footer */}
      <div className="task-card-footer">
        <button className="task-btn-ghost" onClick={onLogs} title={t.tasks.logs}>
          <ScrollText size={14} />
          <span>{t.tasks.logs}</span>
        </button>
        <div className="task-card-actions">
          <button className="task-btn-ghost task-btn-danger" onClick={onDelete} title={t.tasks.deleteTask}>
            <Trash2 size={14} />
          </button>
          {task.status === "running" ? (
            <button className="task-btn task-btn--stop" onClick={onStop}>
              <Square size={13} />
              <span>{t.tasks.stop}</span>
            </button>
          ) : (
            <button className="task-btn task-btn--run" onClick={onRun}>
              <Play size={13} />
              <span>{task.status === "stopped" ? t.tasks.resume : t.tasks.run}</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Create task modal ─────────────────────────────────────────────────────────

interface CreateProps {
  t: ReturnType<typeof useT>["t"];
  onCreated: (task: Task) => void;
  onClose: () => void;
}

function CreateTaskModal({ t, onCreated, onClose }: CreateProps) {
  const [selectedType, setSelectedType] = useState<TaskType | null>(null);
  const [title, setTitle] = useState("");
  const [limit, setLimit] = useState("50");
  const [pollInterval, setPollInterval] = useState("300");
  const [providerId, setProviderId] = useState<string>("");
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [saving, setSaving] = useState(false);
  const [candidates, setCandidates] = useState<Record<string, number | null> | null>(null);

  const batchProviderType = selectedType ? BATCH_PROVIDER_TYPE[selectedType] : undefined;
  const isBatch = !!batchProviderType;
  const providerLabel = batchProviderType
    ? batchProviderType[0].toUpperCase() + batchProviderType.slice(1)
    : "";

  // Fetch candidate counts once on mount
  useEffect(() => {
    getTaskCandidates().then(setCandidates).catch(() => {});
  }, []);

  // Load matching providers when a batch type is selected
  useEffect(() => {
    if (!selectedType) return;
    const wanted = BATCH_PROVIDER_TYPE[selectedType];
    if (!wanted) return;
    listProviders()
      .then(all => {
        const matching = all.filter(p => p.provider_type === wanted && p.enabled);
        setProviders(matching);
        if (matching.length > 0) setProviderId(String(matching[0].id));
      })
      .catch(() => {});
  }, [selectedType]);

  const handleSelectType = (type: TaskType) => {
    setSelectedType(type);
    setTitle(t.tasks.types[type as keyof typeof t.tasks.types] ?? type);
    if (BATCH_PROVIDER_TYPE[type]) {
      setLimit("50");
    }
  };

  const handleCreate = async () => {
    if (!selectedType || !title.trim()) return;
    setSaving(true);
    try {
      const config: Record<string, unknown> = {};
      if (TYPES_WITH_LIMIT.includes(selectedType)) {
        config.limit = parseInt(limit, 10) || 50;
      }
      if (isBatch) {
        if (providerId) config.provider_id = parseInt(providerId, 10);
        config.poll_interval = parseInt(pollInterval, 10) || 300;
      }
      const task = await createTask({ task_type: selectedType, title: title.trim(), config });
      onCreated(task);
    } catch { /* ignore */ } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={t.tasks.selectType} size="md">
      {!selectedType ? (
        <div className="create-type-grid">
          {ALL_TYPES.map(type => (
            <button key={type} className="create-type-card" onClick={() => handleSelectType(type)}>
              <span className="task-type-label task-type-label--lg">
                {TASK_LABELS[type]}
              </span>
              <span className="create-type-name">
                {t.tasks.types[type as keyof typeof t.tasks.types]}
              </span>
              <span className="create-type-desc text-xs text-muted">
                {t.tasks.descriptions[type as keyof typeof t.tasks.descriptions]}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="create-form">
          <button className="task-btn-ghost create-form-back" onClick={() => setSelectedType(null)}>
            <ChevronLeft size={14} /> {t.cancel}
          </button>

          <div className="create-form-desc">
            <p>{t.tasks.detailedDescriptions[selectedType as keyof typeof t.tasks.detailedDescriptions]}</p>
            {TASK_DOC_URLS[selectedType] && (
              <a
                className="create-form-doc-link"
                href={TASK_DOC_URLS[selectedType]}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t.tasks.readDocs}
              </a>
            )}
            <span className="create-form-candidates">
              {candidates === null
                ? t.tasks.candidatesLoading
                : (() => {
                    const count = candidates[selectedType];
                    return count === null || count === undefined
                      ? t.tasks.candidatesUnknown
                      : t.tasks.candidatesCount.replace("{{count}}", String(count));
                  })()}
            </span>
          </div>

          <div className="create-form-field">
            <label className="create-form-label">{t.tasks.taskTitle}</label>
            <input
              className="create-form-input"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder={t.tasks.types[selectedType as keyof typeof t.tasks.types]}
            />
          </div>

          {TYPES_WITH_LIMIT.includes(selectedType) && (
            <div className="create-form-field">
              <label className="create-form-label">{t.tasks.configLimit}</label>
              <input
                className="create-form-input"
                type="number"
                value={limit}
                onChange={e => setLimit(e.target.value)}
                min="1"
                max="1000"
              />
            </div>
          )}

          {isBatch && (
            <>
              <div className="create-form-field">
                <label className="create-form-label">
                  {t.tasks.configProvider.replace("{{provider}}", providerLabel)}
                </label>
                {providers.length === 0 ? (
                  <p className="text-sm text-muted">
                    {t.tasks.noBatchProvider.replace("{{provider}}", providerLabel)}
                  </p>
                ) : (
                  <select
                    className="create-form-input"
                    value={providerId}
                    onChange={e => setProviderId(e.target.value)}
                  >
                    {providers.map(p => (
                      <option key={p.id} value={p.id}>
                        {p.name}{p.model ? ` — ${p.model}` : ""}
                      </option>
                    ))}
                  </select>
                )}
              </div>
              <div className="create-form-field">
                <label className="create-form-label">{t.tasks.configPollInterval}</label>
                <input
                  className="create-form-input"
                  type="number"
                  value={pollInterval}
                  onChange={e => setPollInterval(e.target.value)}
                  min="60"
                  max="3600"
                />
              </div>
            </>
          )}

          <div className="create-form-footer">
            <Button variant="secondary" size="sm" onClick={onClose}>{t.cancel}</Button>
            <Button
              variant="primary"
              size="sm"
              loading={saving}
              onClick={handleCreate}
              disabled={!title.trim() || (isBatch && providers.length === 0)}
            >
              {t.tasks.createTask}
            </Button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ── Logs modal ────────────────────────────────────────────────────────────────

interface LogsModalProps {
  task: Task;
  t: ReturnType<typeof useT>["t"];
  onClose: () => void;
}

function TaskLogsModal({ task, t, onClose }: LogsModalProps) {
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
      <div className="logs-container">
        {loading ? (
          <div className="logs-empty text-muted">{t.loading}</div>
        ) : logs.length === 0 ? (
          <div className="logs-empty text-muted">{t.tasks.logsEmpty}</div>
        ) : (
          logs.map(log => (
            <div key={log.id} className={`log-line log-line--${log.level}`}>
              <span className="log-time text-xs text-muted">
                {log.created_at ? new Date(log.created_at).toLocaleTimeString() : ""}
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

// ── Empty state ───────────────────────────────────────────────────────────────

function TasksEmpty({ t, onAdd }: { t: ReturnType<typeof useT>["t"]; onAdd: () => void }) {
  return (
    <div className="tasks-empty">
      <div className="tasks-empty-icon">⚙️</div>
      <p className="tasks-empty-title">{t.tasks.noTasks}</p>
      <p className="text-muted text-sm">{t.tasks.noTasksHint}</p>
      <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={onAdd}>
        {t.tasks.addTask}
      </Button>
    </div>
  );
}
