import { useEffect, useState } from "react";
import { RefreshCw, Trash2 } from "lucide-react";
import { Button } from "../../ui/Button";
import { useT } from "../../../i18n";
import {
  getUsageSummary, getUsagePivot, listUsage, clearUsage,
} from "../../../api/documents";
import type { UsageSummary, UsagePivot, UsageRow, UsageBreakdown } from "../../../types";
import "./UsageTab.css";

const DIMENSIONS = ["usage_type", "provider_name", "model", "day"] as const;
const METRICS = ["count", "cost", "tokens"] as const;
const PERIODS = ["all", "today", "yesterday"] as const;
type Period = typeof PERIODS[number];

// Day boundaries in UTC, matching the server's `day` grouping (SQLite strftime on stored UTC timestamps).
function periodRange(period: Period): { since?: string; until?: string } {
  if (period === "all") return {};
  const d = new Date();
  if (period === "yesterday") d.setUTCDate(d.getUTCDate() - 1);
  const ymd = d.toISOString().slice(0, 10);
  return { since: `${ymd} 00:00:00`, until: `${ymd} 23:59:59` };
}

function fmtCost(n: number): string {
  return "$" + (n || 0).toFixed(n < 1 ? 4 : 2);
}
function fmtNum(n: number): string {
  return (n || 0).toLocaleString();
}
function fmtMetric(metric: string, v: number): string {
  if (metric === "cost") return fmtCost(v);
  return fmtNum(v);
}

// Simple horizontal CSS bar chart.
function BarChart({ title, data, metric }: { title: string; data: UsageBreakdown[]; metric: "count" | "cost" | "tokens" }) {
  const max = Math.max(1, ...data.map(d => (d[metric] as number)));
  return (
    <div className="usage-chart">
      <h4 className="usage-chart-title">{title}</h4>
      {data.length === 0 && <p className="text-xs text-muted">—</p>}
      {data.slice(0, 12).map(d => (
        <div className="usage-bar-row" key={d.key}>
          <span className="usage-bar-label" title={d.key}>{d.key}</span>
          <div className="usage-bar-track">
            <div className="usage-bar-fill" style={{ width: `${((d[metric] as number) / max) * 100}%` }} />
          </div>
          <span className="usage-bar-value">
            {metric === "cost" ? fmtCost(d.cost) : metric === "tokens" ? fmtNum(d.tokens) : fmtNum(d.count)}
          </span>
        </div>
      ))}
    </div>
  );
}

export function UsageTab() {
  const { t } = useT();
  const u = t.admin.usage;

  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [pivot, setPivot] = useState<UsagePivot | null>(null);
  const [rows, setRows] = useState<UsageRow[]>([]);
  const [row, setRow] = useState<string>("usage_type");
  const [col, setCol] = useState<string>("provider_name");
  const [metric, setMetric] = useState<string>("cost");
  const [period, setPeriod] = useState<Period>("all");
  const [loading, setLoading] = useState(false);

  const dimLabel: Record<string, string> = {
    usage_type: u.dimType, provider_name: u.dimProvider, model: u.dimModel, day: u.dimDay,
  };
  const metricLabel: Record<string, string> = {
    count: u.metricCount, cost: u.metricCost, tokens: u.metricTokens,
  };
  const periodLabel: Record<Period, string> = {
    all: u.periodAll, today: u.periodToday, yesterday: u.periodYesterday,
  };

  const load = () => {
    setLoading(true);
    const range = periodRange(period);
    Promise.all([
      getUsageSummary(range),
      getUsagePivot({ row, col, metric, ...range }),
      listUsage({ limit: 100, ...range }),
    ])
      .then(([s, p, r]) => { setSummary(s); setPivot(p); setRows(r); })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(load, [period]);
  useEffect(() => { getUsagePivot({ row, col, metric, ...periodRange(period) }).then(setPivot).catch(() => {}); }, [row, col, metric]);

  const handleClear = async () => {
    if (!window.confirm(u.clearConfirm)) return;
    await clearUsage();
    load();
  };

  return (
    <div className="admin-section">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div>
          <h3 className="admin-section-title">{u.title}</h3>
          <p className="text-xs text-muted">{u.hint}</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label className="usage-period-select">
            {u.period}
            <select value={period} onChange={e => setPeriod(e.target.value as Period)}>
              {PERIODS.map(p => <option key={p} value={p}>{periodLabel[p]}</option>)}
            </select>
          </label>
          <Button variant="ghost" size="sm" icon={<RefreshCw size={13} />} loading={loading} onClick={load}>
            {u.refresh}
          </Button>
          <Button variant="danger" size="sm" icon={<Trash2 size={13} />} onClick={handleClear}>
            {u.clear}
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="usage-cards">
        <div className="usage-card">
          <span className="usage-card-value">{fmtNum(summary?.total_calls ?? 0)}</span>
          <span className="usage-card-label">{u.totalCalls}</span>
        </div>
        <div className="usage-card usage-card--accent">
          <span className="usage-card-value">{fmtCost(summary?.total_cost ?? 0)}</span>
          <span className="usage-card-label">{u.totalCost}</span>
        </div>
        <div className="usage-card">
          <span className="usage-card-value">{fmtNum(summary?.total_tokens_in ?? 0)}</span>
          <span className="usage-card-label">{u.tokensIn}</span>
        </div>
        <div className="usage-card">
          <span className="usage-card-value">{fmtNum(summary?.total_tokens_out ?? 0)}</span>
          <span className="usage-card-label">{u.tokensOut}</span>
        </div>
      </div>

      {/* Charts */}
      <div className="usage-charts">
        <BarChart title={u.byType} data={summary?.by_type ?? []} metric="count" />
        <BarChart title={u.byProvider} data={summary?.by_provider ?? []} metric="cost" />
        <BarChart title={u.byModel} data={summary?.by_model ?? []} metric="cost" />
        <BarChart title={u.byDay} data={summary?.by_day ?? []} metric="cost" />
      </div>

      {/* Pivot */}
      <div className="usage-pivot-controls">
        <h4 className="usage-chart-title">{u.pivot}</h4>
        <label>{u.rows}
          <select value={row} onChange={e => setRow(e.target.value)}>
            {DIMENSIONS.map(d => <option key={d} value={d}>{dimLabel[d]}</option>)}
          </select>
        </label>
        <label>{u.cols}
          <select value={col} onChange={e => setCol(e.target.value)}>
            {DIMENSIONS.map(d => <option key={d} value={d}>{dimLabel[d]}</option>)}
          </select>
        </label>
        <label>{u.metric}
          <select value={metric} onChange={e => setMetric(e.target.value)}>
            {METRICS.map(m => <option key={m} value={m}>{metricLabel[m]}</option>)}
          </select>
        </label>
      </div>

      {pivot && (
        <div className="usage-pivot-wrap">
          <table className="usage-pivot">
            <thead>
              <tr>
                <th>{dimLabel[pivot.row]} \ {dimLabel[pivot.col]}</th>
                {pivot.col_keys.map(ck => <th key={ck}>{ck}</th>)}
                <th className="usage-pivot-total">{u.total}</th>
              </tr>
            </thead>
            <tbody>
              {pivot.row_keys.map((rk, i) => (
                <tr key={rk}>
                  <th>{rk}</th>
                  {pivot.col_keys.map((ck, j) => (
                    <td key={ck}>{pivot.matrix[i][j] ? fmtMetric(metric, pivot.matrix[i][j]) : ""}</td>
                  ))}
                  <td className="usage-pivot-total">{fmtMetric(metric, pivot.row_totals[i])}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th>{u.total}</th>
                {pivot.col_totals.map((ct, j) => <td key={j} className="usage-pivot-total">{fmtMetric(metric, ct)}</td>)}
                <td className="usage-pivot-total">{fmtMetric(metric, pivot.grand_total)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {/* Recent calls */}
      <h4 className="usage-chart-title">{u.recent}</h4>
      {rows.length === 0 ? (
        <p className="text-xs text-muted">{u.empty}</p>
      ) : (
        <div className="usage-pivot-wrap">
          <table className="usage-pivot usage-recent">
            <thead>
              <tr>
                <th>{u.colTime}</th>
                <th>{u.colType}</th>
                <th>{u.colProviderModel}</th>
                <th>{u.colTokens}</th>
                <th>{u.colCost}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id} className={r.status === "error" ? "usage-row-error" : ""}>
                  <td>{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</td>
                  <td>{r.usage_type}</td>
                  <td>{r.provider_name || r.provider_type}{r.model ? ` · ${r.model}` : ""}</td>
                  <td>{r.tokens_in || r.tokens_out ? `${fmtNum(r.tokens_in)} / ${fmtNum(r.tokens_out)}` : "—"}</td>
                  <td>{r.cost_usd != null ? fmtCost(r.cost_usd) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
