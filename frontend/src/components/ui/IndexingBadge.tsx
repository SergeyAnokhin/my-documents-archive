import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import "./IndexingBadge.css";

interface DocSample {
  filename: string;
  status: "pending" | "error";
}

interface Status {
  total: number;
  pending: number;
  done: number;
  error: number;
  samples: DocSample[];
  mode: string;
}

export function IndexingBadge() {
  const [status, setStatus] = useState<Status | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;

    const poll = async () => {
      try {
        const s = await api.get<Status>("/indexing/status");
        if (active) setStatus(s);
      } catch {
        /* ignore */
      }
    };

    poll();
    const id = setInterval(() => {
      if (status?.pending ?? 1 > 0) poll();
    }, 4000);

    return () => { active = false; clearInterval(id); };
  }, [status?.pending]);

  // Close popover when clicking outside
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  if (!status || status.pending === 0 || status.mode === "manual") return null;

  const previewSamples = status.samples.slice(0, 3);

  const tooltip = [
    `В очереди: ${status.pending}`,
    status.error > 0 ? `Ошибки: ${status.error}` : null,
    ...previewSamples.map(s => `• ${truncate(s.filename, 40)}`),
  ].filter(Boolean).join("\n");

  return (
    <div ref={ref} className="indexing-badge-wrap">
      <div
        className="indexing-badge"
        title={tooltip}
        onClick={() => setOpen(prev => !prev)}
        role="button"
        aria-label="Статус индексирования"
      >
        <span className="indexing-badge-spinner" aria-hidden="true" />
        <span className="indexing-badge-text">{status.pending}</span>
      </div>

      {open && (
        <div className="indexing-popover">
          <div className="indexing-popover-header">Индексирование</div>
          <div className="indexing-popover-stats">
            <span>В очереди: <b>{status.pending}</b></span>
            <span>Готово: <b>{status.done}</b></span>
            {status.error > 0 && (
              <span className="indexing-popover-error">Ошибки: <b>{status.error}</b></span>
            )}
          </div>
          {status.samples.length > 0 && (
            <ul className="indexing-popover-list">
              {status.samples.map((s, i) => (
                <li key={i} className={`indexing-popover-item indexing-popover-item--${s.status}`}>
                  <span className="indexing-popover-dot" />
                  <span className="indexing-popover-name">{s.filename}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
