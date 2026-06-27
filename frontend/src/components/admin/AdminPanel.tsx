import { useState } from "react";
import { BarChart2, Settings, ScrollText, DatabaseBackup, Activity } from "lucide-react";
import { Modal } from "../ui/Modal";
import { useT } from "../../i18n";
import { useAdvancedMode } from "../../contexts/AdvancedModeContext";
import { IndexingTab } from "./tabs/IndexingTab";
import { AITab } from "./tabs/AITab";
import { LogTab } from "./tabs/LogTab";
import { BackupTab } from "./tabs/BackupTab";
import { UsageTab } from "./tabs/UsageTab";
import "./AdminPanel.css";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Tab = "indexing" | "ai" | "log" | "backup" | "usage";

export function AdminPanel({ open, onClose }: Props) {
  const { t } = useT();
  const { advancedMode } = useAdvancedMode();
  const [tab, setTab] = useState<Tab>("indexing");

  // Backup/restore and AI usage are advanced-user-only (super-user) tabs.
  const tabIds: Tab[] = ["indexing", "ai", "log", ...(advancedMode ? ["usage" as Tab, "backup" as Tab] : [])];

  return (
    <Modal open={open} onClose={onClose} size="xl" title={t.admin.title}>
      <div className="admin-layout">
        {/* Sidebar tabs */}
        <nav className="admin-nav">
          {tabIds.map((id) => {
            const icons: Record<Tab, JSX.Element> = {
              indexing: <BarChart2 size={16} />,
              ai:       <Settings size={16} />,
              log:      <ScrollText size={16} />,
              backup:   <DatabaseBackup size={16} />,
              usage:    <Activity size={16} />,
            };
            const labels: Record<Tab, string> = {
              indexing: t.admin.tabs.indexing,
              ai:       t.admin.tabs.ai,
              log:      t.admin.tabs.log,
              backup:   t.admin.tabs.backup,
              usage:    t.admin.tabs.usage,
            };
            return (
              <button
                key={id}
                className={`admin-nav-btn${tab === id ? " active" : ""}`}
                onClick={() => setTab(id)}
              >
                {icons[id]}
                <span>{labels[id]}</span>
              </button>
            );
          })}
        </nav>

        {/* Tab content */}
        <div className="admin-content">
          {tab === "indexing" && <IndexingTab />}
          {tab === "ai"       && <AITab />}
          {tab === "log"      && <LogTab />}
          {tab === "usage"    && <UsageTab />}
          {tab === "backup"   && <BackupTab />}
        </div>
      </div>
    </Modal>
  );
}
