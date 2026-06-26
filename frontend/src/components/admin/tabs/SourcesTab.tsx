import { useState, useEffect } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import { listFolders, addFolder, removeFolder, toggleFolder } from "../../../api/documents";
import type { WatchedFolder } from "../../../types";

export function SourcesTab() {
  const { t } = useT();
  const [folders, setFolders] = useState<WatchedFolder[]>([]);
  const [newPath, setNewPath] = useState("");
  const [adding, setAdding] = useState(false);

  const load = () => listFolders().then(setFolders).catch(() => {});

  useEffect(() => { load(); }, []);

  const handleAdd = async () => {
    if (!newPath.trim()) return;
    setAdding(true);
    try {
      await addFolder(newPath.trim());
      setNewPath("");
      await load();
    } catch {
      /* ignore for now */
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="admin-section">
      <h3 className="admin-section-title">{t.admin.sources.title}</h3>

      {folders.length === 0 ? (
        <p className="text-muted">{t.admin.sources.noFolders}</p>
      ) : (
        <ul className="folder-list">
          {folders.map((f) => (
            <li key={f.id} className="folder-item">
              <span className={`folder-path text-mono text-sm${!f.enabled ? " disabled" : ""}`}>{f.path}</span>
              <div className="folder-actions">
                <button
                  className="icon-btn"
                  onClick={() => toggleFolder(f.id).then(load)}
                  title={f.enabled ? t.enabled : t.disabled}
                >
                  <span className={`status-dot ${f.enabled ? "done" : "pending"}`} />
                </button>
                <button
                  className="icon-btn"
                  onClick={() => removeFolder(f.id).then(load)}
                  title={t.delete}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="folder-add">
        <input
          className="admin-input"
          placeholder={t.admin.sources.folderPath}
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
        />
        <Button variant="primary" size="sm" icon={<Plus size={14} />} loading={adding} onClick={handleAdd}>
          {t.add}
        </Button>
      </div>
    </div>
  );
}
