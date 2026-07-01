import { Plus } from "lucide-react";
import { Button } from "../ui/Button";
import { useT } from "../../i18n";

export function TasksEmpty({ t, onAdd }: { t: ReturnType<typeof useT>["t"]; onAdd: () => void }) {
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
