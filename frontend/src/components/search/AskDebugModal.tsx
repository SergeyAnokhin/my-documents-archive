import { useState } from "react";
import { X, Copy, Check, AlertTriangle } from "lucide-react";
import type { AskDebug } from "../../types";
import { useT } from "../../i18n";
import "./AskDebugModal.css";

interface Props {
  debug: AskDebug;
  onClose: () => void;
}

/** Render the full retrieval trace as plain text for copy/paste. */
function buildDebugText(d: AskDebug): string {
  const lines: string[] = [];
  lines.push(`QUERY: ${d.query}`);
  lines.push(`variants: ${d.query_variants.join(" | ")}`);
  lines.push(
    `depth=${d.depth}  n_retrieve=${d.n_retrieve}  n_send=${d.n_send}  ocr_chars=${d.ocr_chars}`,
  );
  lines.push(
    `embedded=${d.embedded_count}/${d.total_docs} docs   fulltext_matches=${d.fulltext_count}`,
  );
  lines.push(
    `timings(ms): semantic=${d.semantic_ms.toFixed(0)}  fulltext=${d.fulltext_ms.toFixed(0)}  llm=${d.llm_ms.toFixed(0)}  total=${d.total_ms.toFixed(0)}`,
  );
  lines.push(`provider=${d.provider_name ?? "-"}  model=${d.model_name ?? "-"}`);
  if (d.fallback_newest) {
    lines.push("⚠ POOL EMPTY — answered from newest documents (no embeddings / no keyword hits)");
  }
  lines.push("");
  lines.push(`SEMANTIC RANKING (${d.semantic.length} embedded docs scored, closest first):`);
  lines.push("  #   sim     flags        type            file");
  for (const s of d.semantic) {
    const sim = s.similarity != null ? s.similarity.toFixed(3) : "  -  ";
    const flags = [
      s.sent ? "SENT" : s.retrieved ? "retr" : "drop",
      s.in_fulltext ? "+ft" : "   ",
    ].join(" ");
    lines.push(
      `  ${String(s.rank).padEnd(3)} ${sim.padEnd(7)} ${flags.padEnd(12)} ${(s.document_type ?? "-").padEnd(15)} ${s.filename} [id=${s.doc_id}]`,
    );
  }
  lines.push("");
  lines.push(`SENT TO LLM (ids): ${d.sent_ids.join(", ") || "(none)"}`);
  lines.push(`RETRIEVED (ids):   ${d.retrieved_ids.join(", ") || "(none)"}`);
  lines.push(`FULLTEXT (ids):    ${d.fulltext_ids.join(", ") || "(none)"}`);
  lines.push("");
  lines.push(`CONTEXT SENT TO LLM (${d.context_chars} chars)`);
  lines.push(`--- SYSTEM PROMPT ---\n${d.system_prompt}`);
  lines.push(`--- USER PROMPT ---\n${d.user_prompt}`);
  return lines.join("\n");
}

export function AskDebugModal({ debug, onClose }: Props) {
  const { t } = useT();
  const [copied, setCopied] = useState(false);

  const copyAll = async () => {
    try {
      await navigator.clipboard.writeText(buildDebugText(debug));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  const td = t.aiSearch.debug;

  return (
    <div className="dbg-overlay" onClick={onClose}>
      <div className="dbg-modal" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="dbg-header">
          <span className="dbg-title">{td.title}</span>
          <button type="button" className="dbg-copy" onClick={copyAll}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? td.copied : td.copy}
          </button>
          <button type="button" className="dbg-close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="dbg-body">
          {/* Fallback warning — the key diagnostic */}
          {debug.fallback_newest && (
            <div className="dbg-warn">
              <AlertTriangle size={16} />
              <span>{td.fallbackWarning}</span>
            </div>
          )}

          {/* Query */}
          <div className="dbg-query">“{debug.query}”</div>
          <div className="dbg-variants">{debug.query_variants.join("  |  ")}</div>

          {/* Summary chips */}
          <div className="dbg-stats">
            <span className="dbg-stat">
              <b>{debug.embedded_count}</b>/{debug.total_docs} {td.embedded}
            </span>
            <span className="dbg-stat">
              {td.fulltext}: <b>{debug.fulltext_count}</b>
            </span>
            <span className="dbg-stat">
              depth {debug.depth} · retrieve {debug.n_retrieve} · send {debug.n_send}
            </span>
            <span className="dbg-stat">
              {debug.model_name ?? "-"}
            </span>
            <span className="dbg-stat">
              {td.total}: {debug.total_ms.toFixed(0)}ms
            </span>
          </div>

          {/* Semantic ranking table */}
          <div className="dbg-section-title">
            {td.ranking} ({debug.semantic.length})
          </div>
          {debug.semantic.length === 0 ? (
            <div className="dbg-empty">{td.noEmbeddings}</div>
          ) : (
            <table className="dbg-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{td.sim}</th>
                  <th>{td.status}</th>
                  <th>{td.type}</th>
                  <th>{td.file}</th>
                </tr>
              </thead>
              <tbody>
                {debug.semantic.map((s) => (
                  <tr
                    key={s.doc_id}
                    className={s.sent ? "dbg-row-sent" : s.retrieved ? "dbg-row-retr" : "dbg-row-drop"}
                  >
                    <td>{s.rank}</td>
                    <td className="dbg-sim">{s.similarity != null ? s.similarity.toFixed(3) : "—"}</td>
                    <td>
                      <span className={`dbg-badge dbg-badge--${s.sent ? "sent" : s.retrieved ? "retr" : "drop"}`}>
                        {s.sent ? td.sent : s.retrieved ? td.retrieved : td.dropped}
                      </span>
                      {s.in_fulltext && <span className="dbg-badge dbg-badge--ft">ft</span>}
                    </td>
                    <td className="dbg-type">{s.document_type ?? "—"}</td>
                    <td className="dbg-file">{s.filename}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Prompt sent to LLM */}
          <details className="dbg-details">
            <summary>{td.prompt} ({debug.context_chars} chars)</summary>
            <pre className="dbg-pre">{debug.system_prompt}{"\n\n"}{debug.user_prompt}</pre>
          </details>
        </div>
      </div>
    </div>
  );
}
