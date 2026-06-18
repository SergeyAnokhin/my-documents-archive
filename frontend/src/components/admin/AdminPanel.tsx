import { useState } from "react";
import { BarChart2, Folder, Settings, ScrollText } from "lucide-react";
import { Modal } from "../ui/Modal";
import { useT } from "../../i18n";
import { IndexingTab } from "./tabs/IndexingTab";
import { SourcesTab } from "./tabs/SourcesTab";
import { AITab } from "./tabs/AITab";
import { LogTab } from "./tabs/LogTab";
import "./AdminPanel.css";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Tab = "sources" | "indexing" | "ai" | "log";

export function AdminPanel({ open, onClose }: Props) {
  const { t } = useT();
  const [tab, setTab] = useState<Tab>("indexing");

  return (
    <Modal open={open} onClose={onClose} size="lg" title={t.admin.title}>
      <div className="admin-layout">
        {/* Sidebar tabs */}
        <nav className="admin-nav">
          {(["indexing", "sources", "ai", "log"] as Tab[]).map((id) => {
            const icons: Record<Tab, JSX.Element> = {
              indexing: <BarChart2 size={16} />,
              sources:  <Folder size={16} />,
              ai:       <Settings size={16} />,
              log:      <ScrollText size={16} />,
            };
            const labels: Record<Tab, string> = {
              indexing: t.admin.tabs.indexing,
              sources:  t.admin.tabs.sources,
              ai:       t.admin.tabs.ai,
              log:      t.admin.tabs.log,
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
          {tab === "sources"  && <SourcesTab />}
          {tab === "ai"       && <AITab />}
          {tab === "log"      && <LogTab />}
        </div>
      </div>
    </Modal>
  );
}
