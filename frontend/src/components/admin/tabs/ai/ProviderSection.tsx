import { useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "../../../ui/Button";
import { useT } from "../../../../i18n";
import { toggleProvider, removeProvider, updateProviderOrder } from "../../../../api/documents";
import type { AIProvider, ArenaRating } from "../../../../types";
import { ProviderRow } from "./ProviderRow";
import { AddProviderForm } from "./AddProviderForm";

export function ProviderSection({
  title,
  hint,
  providers,
  taskType,
  ratings,
  onReload,
}: {
  title: string;
  hint: string;
  providers: AIProvider[];
  taskType: "analysis" | "vision" | "premium";
  ratings: Record<string, ArenaRating>;
  onReload: () => void;
}) {
  const { t } = useT();
  const [showForm, setShowForm] = useState(false);

  const moveProvider = async (index: number, direction: "up" | "down") => {
    const swapIndex = direction === "up" ? index - 1 : index + 1;
    if (swapIndex < 0 || swapIndex >= providers.length) return;
    const a = providers[index];
    const b = providers[swapIndex];
    const orderA = a.sort_order !== b.sort_order ? a.sort_order : index * 10;
    const orderB = a.sort_order !== b.sort_order ? b.sort_order : swapIndex * 10;
    await updateProviderOrder(a.id, orderB);
    await updateProviderOrder(b.id, orderA);
    onReload();
  };

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ marginBottom: 6 }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{title}</span>
        <p className="text-xs text-muted" style={{ marginTop: 2 }}>{hint}</p>
      </div>

      {providers.length === 0 ? (
        <p className="text-muted" style={{ fontSize: 13, marginBottom: 8 }}>
          {t.admin.ai.noProviders}
        </p>
      ) : (
        <ul className="provider-list">
          {providers.map((p, i) => (
            <ProviderRow
              key={p.id}
              provider={p}
              isFirst={i === 0}
              isLast={i === providers.length - 1}
              ratings={ratings}
              forVision={taskType === "vision"}
              onToggle={() => toggleProvider(p.id).then(onReload)}
              onDelete={() => removeProvider(p.id).then(onReload)}
              onMoveUp={() => moveProvider(i, "up")}
              onMoveDown={() => moveProvider(i, "down")}
              onReload={onReload}
            />
          ))}
        </ul>
      )}

      {!showForm ? (
        <Button variant="secondary" size="sm" icon={<Plus size={14} />}
          onClick={() => setShowForm(true)} style={{ marginTop: 4 }}>
          {t.admin.ai.addProvider}
        </Button>
      ) : (
        <AddProviderForm
          taskType={taskType}
          ratings={ratings}
          onSaved={() => { setShowForm(false); onReload(); }}
          onCancel={() => setShowForm(false)}
        />
      )}
    </div>
  );
}
