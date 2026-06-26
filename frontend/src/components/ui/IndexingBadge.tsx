import { useEffect, useState } from "react";
import { api } from "../../api/client";
import "./IndexingBadge.css";

interface Status {
  total: number;
  pending: number;
  done: number;
  error: number;
}

export function IndexingBadge() {
  const [status, setStatus] = useState<Status | null>(null);

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
    // Poll every 4s only while there are pending docs
    const id = setInterval(() => {
      if (status?.pending ?? 1 > 0) poll();
    }, 4000);

    return () => { active = false; clearInterval(id); };
  }, [status?.pending]);

  if (!status || status.pending === 0) return null;

  return (
    <div className="indexing-badge" title={`${status.pending} document(s) being indexed`}>
      <span className="indexing-badge-spinner" aria-hidden="true" />
      <span className="indexing-badge-text">{status.pending}</span>
    </div>
  );
}
