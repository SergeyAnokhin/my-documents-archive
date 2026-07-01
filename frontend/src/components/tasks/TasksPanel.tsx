import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, Square, Layers } from "lucide-react";
import { Modal } from "../ui/Modal";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";
import {
  listTasks, deleteTask, runTask, stopTask, stopAllTasks, updateTask,
} from "../../api/documents";
import type { Task, TaskType } from "../../types";
import { TaskCard } from "./TaskCard";
import { CreateTaskModal, type TaskPreCreate } from "./CreateTaskModal";
import { TaskLogsModal } from "./TaskLogsModal";
import { BatchMonitorModal } from "./BatchMonitorModal";
import { TasksEmpty } from "./TasksEmpty";
import { BATCH_TASK_TYPES } from "./taskConfig";
import "./TasksPanel.css";

export type { TaskPreCreate };

interface Props {
  open: boolean;
  onClose: () => void;
  preCreate?: TaskPreCreate | null;
  onPreCreateConsumed?: () => void;
}

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
    load();
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
  const hasBatchTasks = tasks.some(tk => BATCH_TASK_TYPES.includes(tk.task_type as TaskType));

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
