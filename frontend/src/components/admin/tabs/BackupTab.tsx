import { useState, useEffect } from "react";
import { RefreshCw, RotateCcw } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import { listBackups, restoreBackup } from "../../../api/documents";
import type { BackupInfo } from "../../../types";

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function BackupTab() {
  const { t } = useT();
  const b = t.admin.backup;
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);
  const [msg, setMsg] = useState("");

  const load = () => {
    setLoading(true);
    listBackups().then(setBackups).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const flash = (text: string) => { setMsg(text); setTimeout(() => setMsg(""), 5000); };

  const handleRestore = async (name: string) => {
    if (!window.confirm(b.confirm.replace("{{name}}", name))) return;
    setRestoring(name);
    try {
      await restoreBackup(name);
      flash(b.restored.replace("{{name}}", name));
    } catch (e: unknown) {
      flash(e instanceof Error ? e.message : t.error);
    } finally {
      setRestoring(null);
    }
  };

  return (
    <div className="admin-section">
      <h3 className="admin-section-title">{b.title}</h3>
      <p className="text-xs text-muted" style={{ marginBottom: 12 }}>{b.hint}</p>

      <div className="admin-actions" style={{ marginBottom: 12 }}>
        <Button variant="secondary" icon={<RefreshCw size={15} />} loading={loading} onClick={load}>
          {b.refresh}
        </Button>
      </div>

      {msg && <p className="admin-msg">{msg}</p>}

      {backups.length === 0 ? (
        <p className="text-sm text-muted">{b.empty}</p>
      ) : (
        <ul className="backup-list">
          {backups.map((bk) => (
            <li key={bk.name} className="backup-row">
              <div className="backup-meta">
                <span className="backup-name">{bk.name}</span>
                <span className="text-xs text-muted">
                  {new Date(bk.modified).toLocaleString()} · {fmtSize(bk.size)}
                </span>
              </div>
              <Button
                variant="danger"
                size="sm"
                icon={<RotateCcw size={14} />}
                loading={restoring === bk.name}
                disabled={restoring !== null}
                onClick={() => handleRestore(bk.name)}
              >
                {b.restore}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
