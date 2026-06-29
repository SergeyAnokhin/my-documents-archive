import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, Square, Play, ScrollText, Trash2, X, GripVertical, ChevronLeft, Layers, Download, Clock } from "lucide-react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";
import {
  listTasks, createTask, deleteTask, runTask, stopTask,
  stopAllTasks, getTaskLogs, updateTask, listProviders, getTaskCandidates, getScopeCount,
  resumeBatchTask, getBatchResultUrl, getCompressCandidates,
} from "../../api/documents";
import type { AIProvider, Task, TaskLog, TaskType } from "../../types";
import "./TasksPanel.css";

// ── Duration formatter ────────────────────────────────────────────────────────

function formatDuration(ms: number, h: string, m: string, s: string): string {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(sec / 3600);
  const mins = Math.floor((sec % 3600) / 60);
  const secs = sec % 60;
  if (hours > 0) return `${hours}${h} ${mins}${m}`;
  if (mins > 0) return `${mins}${m} ${secs}${s}`;
  return `${secs}${s}`;
}

// ── Task type short labels ────────────────────────────────────────────────────

const TASK_LABELS: Record<TaskType, string> = {
  index_unindexed:         "OCR",
  sync_library:            "SYNC",
  reclassify_unclassified: "CLASSIFY",
  reclassify_all:          "RECLASSIFY",
  recluster:               "RECLUSTER",
  batch_ocr_mistral:       "BATCH OCR",
  batch_ocr_gemini:        "BATCH AI",
  embed_missing:           "EMBED",
  fix_quality:             "FIX",
  cleanup_missing:         "CLEANUP",
  compress_images:         "COMPRESS",
};

const ALL_TYPES: TaskType[] = [
  "index_unindexed",
  "sync_library",
  "reclassify_unclassified",
  "reclassify_all",
  "recluster",
  "batch_ocr_mistral",
  "batch_ocr_gemini",
  "embed_missing",
  "cleanup_missing",
  "compress_images",
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
  reclassify_unclassified: "gemini",
  reclassify_all:          "gemini",
  batch_ocr_mistral:       "mistral",
  batch_ocr_gemini:        "gemini",
};

// Default poll interval (seconds) per provider type.
// Edit here to change the pre-filled value in the create form per provider.
const BATCH_POLL_DEFAULTS: Record<string, number> = {
  mistral: 30,
  gemini:  30,
};

// Tasks that have a scope selector (cumulative level filter).
const TYPES_WITH_SCOPE: TaskType[] = ["batch_ocr_mistral", "batch_ocr_gemini"];

// Tasks that expose a "force full recompute" checkbox.
const TYPES_WITH_FORCE: TaskType[] = ["embed_missing"];

// External documentation links for task types that have official provider docs.
const TASK_DOC_URLS: Partial<Record<TaskType, string>> = {
  reclassify_unclassified: "https://ai.google.dev/gemini-api/docs/batch-mode",
  reclassify_all:          "https://ai.google.dev/gemini-api/docs/batch-mode",
  batch_ocr_mistral:       "https://docs.mistral.ai/capabilities/batch/",
  batch_ocr_gemini:        "https://ai.google.dev/gemini-api/docs/batch-mode",
};

// Links to provider batch consoles — shown while the task is running.
const BATCH_CONSOLE_URLS: Partial<Record<TaskType, string>> = {
  batch_ocr_mistral: "https://console.mistral.ai/build/batches",
};

// Batch task types that have a remote job and can be monitored / resumed
const BATCH_TASK_TYPES: TaskType[] = [
  "reclassify_unclassified", "reclassify_all",
  "batch_ocr_mistral", "batch_ocr_gemini",
];

// ── Props ─────────────────────────────────────────────────────────────────────

export interface TaskPreCreate {
  taskType: TaskType;
  title: string;
  config: Record<string, unknown>;
  candidateCount?: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  preCreate?: TaskPreCreate | null;
  onPreCreateConsumed?: () => void;
}

// ── Main panel ────────────────────────────────────────────────────────────────

export function TasksPanel({ open, onClose, preCreate, onPreCreateConsumed }: Props) {
  const { t } = useT();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showBatchMonitor, setShowBatchMonitor] = useState(false);
  const [logsTask, setLogsTask] = useState<Task | null>(null);
  const [draggedId, setDraggedId] = useState<number | null>(null);
  const [dragOverId, setDragOverId] = useState<number | null>(null);
  const [startingId, setStartingId] = useState<number | null>(null);
  const [now, setNow] = useState(Date.now());
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

  // Auto-open CreateTaskModal when a pre-create config arrives
  useEffect(() => {
    if (open && preCreate) {
      setShowCreate(true);
    }
  }, [open, preCreate]);

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

  // Tick every second to update elapsed time on running tasks
  useEffect(() => {
    const hasRunning = tasks.some(tk => tk.status === "running");
    if (!hasRunning) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [tasks]);

  const handleRun = async (task: Task) => {
    setStartingId(task.id);
    try {
      await runTask(task.id);
      await load();
    } finally {
      setStartingId(null);
    }
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
    onPreCreateConsumed?.();
  };

  const handleCloseCreate = () => {
    setShowCreate(false);
    onPreCreateConsumed?.();
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
  const hasBatchTasks = tasks.some(tk => BATCH_TASK_TYPES.includes(tk.task_type));

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
            {hasBatchTasks && (
              <Button variant="secondary" size="sm" icon={<Layers size={14} />} onClick={() => setShowBatchMonitor(true)}>
                {t.tasks.batchMonitor}
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
                now={now}
                isDragging={draggedId === task.id}
                isDragOver={dragOverId === task.id}
                isStarting={startingId === task.id}
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
          onClose={handleCloseCreate}
          initialType={preCreate?.taskType}
          initialTitle={preCreate?.title}
          initialConfig={preCreate?.config}
          initialCandidateCount={preCreate?.candidateCount}
        />
      )}

      {showBatchMonitor && (
        <BatchMonitorModal
          tasks={tasks}
          t={t}
          onRefresh={load}
          onLogs={(task) => { setShowBatchMonitor(false); setLogsTask(task); }}
          onClose={() => setShowBatchMonitor(false)}
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

function TaskCard({
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
          <span className="text-xs text-muted" style={{ fontFamily: "var(--font-mono)" }}>
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
          ) : (
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

// ── Create task modal ─────────────────────────────────────────────────────────

interface CreateProps {
  t: ReturnType<typeof useT>["t"];
  onCreated: (task: Task) => void;
  onClose: () => void;
  initialType?: TaskType;
  initialTitle?: string;
  initialConfig?: Record<string, unknown>;
  initialCandidateCount?: number;
}

function CreateTaskModal({ t, onCreated, onClose, initialType, initialTitle, initialConfig, initialCandidateCount }: CreateProps) {
  const [selectedType, setSelectedType] = useState<TaskType | null>(initialType ?? null);
  const [title, setTitle] = useState(initialTitle ?? "");
  const [limit, setLimit] = useState("50");
  const [pollInterval, setPollInterval] = useState("30");
  const [providerId, setProviderId] = useState<string>("");
  const [providers, setProviders] = useState<AIProvider[]>([]);
  const [saving, setSaving] = useState(false);
  const [forceEmbed, setForceEmbed] = useState(false);
  const [candidates, setCandidates] = useState<Record<string, number | null> | null>(null);
  const [scope, setScope] = useState(1);
  const [scopeCount, setScopeCount] = useState<number | null>(null);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [maxLongSide, setMaxLongSide] = useState("1024");
  const [compressCount, setCompressCount] = useState<{ count: number; total_images: number } | null>(null);
  const [compressLoading, setCompressLoading] = useState(false);
  const compressDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const batchProviderType = selectedType ? BATCH_PROVIDER_TYPE[selectedType] : undefined;
  const isBatch = !!batchProviderType;
  const hasScope = selectedType ? TYPES_WITH_SCOPE.includes(selectedType) : false;
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

  // Fetch scope count when scope or task type changes (only for scope-aware tasks)
  useEffect(() => {
    if (!selectedType || !TYPES_WITH_SCOPE.includes(selectedType)) return;
    setScopeLoading(true);
    setScopeCount(null);
    getScopeCount(selectedType, scope)
      .then(data => setScopeCount(data.count))
      .catch(() => setScopeCount(null))
      .finally(() => setScopeLoading(false));
  }, [selectedType, scope]);

  // Fetch compress candidate count with debounce when threshold changes
  useEffect(() => {
    if (selectedType !== "compress_images") return;
    const threshold = parseInt(maxLongSide, 10);
    if (!threshold || threshold < 1) return;
    if (compressDebounceRef.current) clearTimeout(compressDebounceRef.current);
    setCompressLoading(true);
    compressDebounceRef.current = setTimeout(() => {
      getCompressCandidates(threshold)
        .then(data => setCompressCount(data))
        .catch(() => setCompressCount(null))
        .finally(() => setCompressLoading(false));
    }, 600);
    return () => {
      if (compressDebounceRef.current) clearTimeout(compressDebounceRef.current);
    };
  }, [selectedType, maxLongSide]);

  const handleSelectType = (type: TaskType) => {
    setSelectedType(type);
    setTitle(t.tasks.types[type as keyof typeof t.tasks.types] ?? type);
    setForceEmbed(false);
    setScope(1);
    setScopeCount(null);
    setMaxLongSide("1024");
    setCompressCount(null);
    const providerType = BATCH_PROVIDER_TYPE[type];
    if (providerType) {
      setLimit("50");
      setPollInterval(String(BATCH_POLL_DEFAULTS[providerType] ?? 30));
    }
  };

  const handleCreate = async () => {
    if (!selectedType || !title.trim()) return;
    setSaving(true);
    try {
      const config: Record<string, unknown> = { ...(initialConfig ?? {}) };
      if (TYPES_WITH_LIMIT.includes(selectedType)) {
        config.limit = parseInt(limit, 10) || 50;
      }
      if (hasScope) {
        config.scope = scope;
      }
      if (isBatch) {
        if (providerId) config.provider_id = parseInt(providerId, 10);
        config.poll_interval = parseInt(pollInterval, 10) || (batchProviderType ? BATCH_POLL_DEFAULTS[batchProviderType] : 30) || 30;
      }
      if (selectedType === "compress_images") {
        config.max_long_side = parseInt(maxLongSide, 10) || 1024;
      }
      if (TYPES_WITH_FORCE.includes(selectedType) && forceEmbed) {
        config.force = true;
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
            {!hasScope && (
              <span className="create-form-candidates">
                {initialCandidateCount !== undefined
                  ? t.tasks.candidatesCount.replace("{{count}}", String(initialCandidateCount))
                  : candidates === null
                    ? t.tasks.candidatesLoading
                    : (() => {
                        const count = candidates[selectedType];
                        return count === null || count === undefined
                          ? t.tasks.candidatesUnknown
                          : t.tasks.candidatesCount.replace("{{count}}", String(count));
                      })()}
              </span>
            )}
          </div>

          {selectedType === "compress_images" && (
            <div className="create-form-field">
              <label className="create-form-label">{t.tasks.compressMaxSideLabel}</label>
              <input
                className="create-form-input"
                type="number"
                value={maxLongSide}
                onChange={e => setMaxLongSide(e.target.value)}
                min="100"
                max="10000"
              />
              <span className="create-form-candidates">
                {compressLoading
                  ? t.tasks.candidatesLoading
                  : compressCount === null
                    ? t.tasks.candidatesLoading
                    : t.tasks.compressCandidatesCount
                        .replace("{{count}}", String(compressCount.count))
                        .replace("{{total}}", String(compressCount.total_images))}
              </span>
            </div>
          )}

          {hasScope && (
            <div className="create-form-field">
              <label className="create-form-label">{t.tasks.scopeLabel}</label>
              <div className="create-scope-options">
                {([1, 2, 3, 4] as const).map(lvl => (
                  <label key={lvl} className={`create-scope-option${scope === lvl ? " create-scope-option--selected" : ""}`}>
                    <input
                      type="radio"
                      name="scope"
                      value={lvl}
                      checked={scope === lvl}
                      onChange={() => setScope(lvl)}
                    />
                    {t.tasks.scopeOptions[String(lvl) as keyof typeof t.tasks.scopeOptions]}
                  </label>
                ))}
              </div>
              <span className="create-form-candidates">
                {scopeLoading
                  ? t.tasks.scopeCountLoading
                  : scopeCount === null
                    ? ""
                    : t.tasks.scopeCount.replace("{{count}}", String(scopeCount))}
              </span>
            </div>
          )}

          {TYPES_WITH_FORCE.includes(selectedType) && (
            <label className="create-form-force-label">
              <input
                type="checkbox"
                checked={forceEmbed}
                onChange={e => setForceEmbed(e.target.checked)}
              />
              <span>{t.tasks.forceEmbedLabel}</span>
              <span className="create-form-force-hint text-xs text-muted">{t.tasks.forceEmbedHint}</span>
            </label>
          )}

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

// ── Batch monitor modal ───────────────────────────────────────────────────────

interface BatchMonitorProps {
  tasks: Task[];
  t: ReturnType<typeof useT>["t"];
  onRefresh: () => Promise<void>;
  onLogs: (task: Task) => void;
  onClose: () => void;
}

function BatchMonitorModal({ tasks, t, onRefresh, onLogs, onClose }: BatchMonitorProps) {
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
                    ) : canResume ? (
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
                    )}
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
