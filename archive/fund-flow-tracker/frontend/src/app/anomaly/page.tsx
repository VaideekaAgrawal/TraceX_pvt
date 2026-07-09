"use client";

import { useEffect, useState } from "react";
import { api, AnomalyData } from "@/lib/api";
import { Card, StatCard, Loader, Badge, InfoTooltip } from "@/components/ui";
import { formatINR, getRiskBg, getPriorityColor, getRoleIcon } from "@/lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from "recharts";

function AIExplanationPanel({ accountId }: { accountId: string }) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [shown, setShown] = useState(false);

  const generate = async () => {
    if (shown && explanation) { setShown(false); return; }
    setShown(true);
    if (explanation) return;
    setLoading(true);
    try {
      const res = await api.getAccountExplanation(accountId);
      setExplanation(res.explanation);
    } catch {
      setExplanation("Could not generate explanation. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-2">
      <button
        onClick={generate}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-violet-600/20 border border-violet-500/30 text-xs text-violet-300 hover:bg-violet-600/30 transition-colors"
      >
        <span>🤖</span>
        <span>{shown && explanation ? "Hide Explanation" : "Why flagged? (AI)"}</span>
      </button>
      {shown && (
        <div className="mt-2 p-3 rounded-lg bg-violet-500/5 border border-violet-500/20">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-violet-300">
              <span className="h-3 w-3 border border-violet-400/40 border-t-violet-400 rounded-full animate-spin" />
              Generating AI explanation...
            </div>
          ) : (
            <p className="text-xs text-slate-300 leading-relaxed">{explanation}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function AnomalyPage() {
  const [data, setData] = useState<AnomalyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [queuePage, setQueuePage] = useState(0);
  const [queueFilter, setQueueFilter] = useState("");
  const [queuePriorityFilter, setQueuePriorityFilter] = useState<string>("ALL");
  const QUEUE_PER_PAGE = 15;

  useEffect(() => {
    api
      .getAnomaly()
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Loader />;
  if (!data) return <p className="text-slate-400 p-8">Failed to load anomaly data.</p>;

  // Stats
  const queue = data.investigation_queue || [];
  const scores = data.anomaly_scores || [];
  const speedAlerts = data.speed_alerts || [];

  const totalQueue = queue.length;
  const p1Count = queue.filter((i) => i.priority === "P1").length;
  const p2Count = queue.filter((i) => i.priority === "P2").length;
  const speedAlertCount = speedAlerts.length;

  // Histogram bins
  const bins = Array.from({ length: 10 }, (_, i) => ({
    range: `${i * 10}-${(i + 1) * 10}`,
    count: 0,
    high: i >= 7,
  }));
  scores.forEach(({ anomaly_score }) => {
    const idx = Math.min(Math.floor(anomaly_score / 10), 9);
    bins[idx].count++;
  });

  function anomalyLabel(score: number): string {
    if (score >= 70) return "Unusual behaviour";
    if (score >= 40) return "Moderate deviation";
    return "Within normal range";
  }


  // Investigation queue sorted
  const priorityOrder: Record<string, number> = { P1: 0, P2: 1, P3: 2, P4: 3 };
  const sortedQueue = [...queue].sort((a, b) => {
    const pd = (priorityOrder[a.priority] ?? 9) - (priorityOrder[b.priority] ?? 9);
    if (pd !== 0) return pd;
    return b.risk_score - a.risk_score;
  });

  // Speed alert colors
  const speedCategoryColor = (cat: string) => {
    switch (cat) {
      case "ABNORMAL":
        return "border-red-500/50 bg-red-500/10";
      case "VERY_FAST":
        return "border-orange-500/50 bg-orange-500/10";
      case "FAST":
        return "border-yellow-500/50 bg-yellow-500/10";
      default:
        return "border-slate-700/50 bg-slate-800";
    }
  };


  return (
    <div className="min-h-screen bg-[#0b1120] p-6 space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Anomaly Detection</h1>
        <p className="text-sm text-slate-400 mt-1">
          ML-powered fraud detection &amp; investigation queue
        </p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total in Queue" value={totalQueue} icon="📋" color="blue" />
        <StatCard label="P1 Critical" value={p1Count} icon="🚨" color="red" />
        <StatCard label="P2 High" value={p2Count} icon="⚠️" color="orange" />
        <StatCard label="Speed Alerts" value={speedAlertCount} icon="⚡" color="yellow" />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Anomaly Score Distribution */}
        <Card>
          <h3 className="text-sm font-semibold text-slate-300 mb-4">
            Anomaly Score Distribution
            <InfoTooltip text="Score distribution from Isolation Forest trained on 28 behavioral features (transaction velocity, amount variance, channel diversity, etc.). Scores 70+ indicate unusually atypical behavior." />
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={bins}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="range" tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <Tooltip
                contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #334155", borderRadius: 8 }}
                labelStyle={{ color: "#e2e8f0" }}
                itemStyle={{ color: "#e2e8f0" }}
              />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {bins.map((entry, idx) => (
                  <Cell key={idx} fill={entry.high ? "#ef4444" : "#3b82f6"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        {/* System-Wide Risk Signals — aggregated from P1/P2 investigation queue indicators */}
        <Card>
          <h3 className="text-sm font-semibold text-slate-300 mb-2">System-Wide Risk Signals<InfoTooltip text="Aggregated indicator frequency across all P1 and P2 accounts. Shows which detection signals are most prevalent — useful for understanding systemic risk patterns." /></h3>
          <p className="text-xs text-slate-500 mb-3">Most common indicators across Priority 1 &amp; 2 accounts</p>
          {(() => {
            const indicatorCounts: Record<string, number> = {};
            queue
              .filter((i) => i.priority === "P1" || i.priority === "P2")
              .forEach((i) => {
                (i.indicators ?? []).forEach((ind: string) => {
                  indicatorCounts[ind] = (indicatorCounts[ind] || 0) + 1;
                });
              });
            const sorted = Object.entries(indicatorCounts)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 8);
            if (sorted.length === 0) {
              return <p className="text-xs text-slate-600">No indicators detected yet. Upload data to see signals.</p>;
            }
            const maxCount = sorted[0]?.[1] || 1;
            return (
              <div className="space-y-2.5">
                {sorted.map(([indicator, count]) => (
                  <div key={indicator}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs text-slate-300">{indicator}</span>
                      <span className="text-xs text-slate-500">{count} account{count !== 1 ? "s" : ""}</span>
                    </div>
                    <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-amber-500 to-red-500"
                        style={{ width: `${(count / maxCount) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            );
          })()}
        </Card>
      </div>

      {/* Investigation Priority Queue */}
      <Card>
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <h3 className="text-sm font-semibold text-slate-300">
            Investigation Priority Queue
          </h3>
          <div className="flex items-center gap-2 flex-wrap">
            <input
              type="text"
              value={queueFilter}
              onChange={(e) => { setQueueFilter(e.target.value); setQueuePage(0); }}
              placeholder="Filter by Account ID..."
              className="px-3 py-1.5 bg-slate-800 border border-slate-700 rounded text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 w-48"
            />
            <div className="flex items-center gap-1">
              {["ALL", "P1", "P2", "P3", "P4"].map((p) => (
                <button
                  key={p}
                  onClick={() => { setQueuePriorityFilter(p); setQueuePage(0); }}
                  className={`px-2 py-1 text-[10px] rounded-full font-medium transition ${
                    queuePriorityFilter === p ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        </div>
        {(() => {
          const filtered = sortedQueue
            .filter((item) => queuePriorityFilter === "ALL" || item.priority === queuePriorityFilter)
            .filter((item) => !queueFilter || item.account_id.toLowerCase().includes(queueFilter.toLowerCase()));
          const totalPages = Math.ceil(filtered.length / QUEUE_PER_PAGE);
          const paged = filtered.slice(queuePage * QUEUE_PER_PAGE, (queuePage + 1) * QUEUE_PER_PAGE);
          return (
            <>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700/50 text-left text-xs text-slate-400 uppercase tracking-wider">
                <th className="pb-3 pr-3">Priority<InfoTooltip text="P1=Critical, act today. P2=High, review within 24h. P3=Medium, review this week. P4=Low, monitor. Priority combines risk score, confidence level, and number of detection signals." /></th>
                <th className="pb-3 pr-3">Account ID</th>
                <th className="pb-3 pr-3">Risk Score</th>
                <th className="pb-3 pr-3">Confidence</th>
                <th className="pb-3 pr-3">Role</th>
                <th className="pb-3 pr-3">Behaviour</th>
                <th className="pb-3 pr-3">Detection Signals & AI Analysis</th>
                <th className="pb-3 pr-3">Total Amount</th>
                <th className="pb-3">City</th>
              </tr>
            </thead>
            <tbody>
              {paged.map((item) => (
                <tr
                  key={item.account_id}
                  className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors"
                >
                  <td className="py-3 pr-3">
                    <span
                      className={`inline-flex items-center justify-center rounded px-2 py-0.5 text-xs font-bold ${getPriorityColor(item.priority)}`}
                    >
                      {item.priority}
                    </span>
                  </td>
                  <td className="py-3 pr-3">
                    <a
                      href={`/graph?account=${item.account_id}`}
                      className="text-blue-400 hover:text-blue-300 font-mono text-xs"
                    >
                      {item.account_id}
                    </a>
                  </td>
                  <td className="py-3 pr-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-2 rounded-full bg-slate-700 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-yellow-500 to-red-500"
                          style={{ width: `${item.risk_score}%` }}
                        />
                      </div>
                      <span className="text-xs text-slate-300">{item.risk_score.toFixed(1)}</span>
                    </div>
                  </td>
                  <td className="py-3 pr-3 text-xs text-slate-300">
                    {item.confidence_level} — {item.confidence_count} signal{item.confidence_count !== 1 ? "s" : ""}
                  </td>
                  <td className="py-3 pr-3 text-xs">
                    <span className="mr-1">{getRoleIcon(item.role)}</span>
                    <span className="text-slate-300">{item.role}</span>
                  </td>
                  <td className="py-3 pr-3 text-xs text-slate-300">
                    {anomalyLabel(item.anomaly_score)}
                  </td>
                  <td className="py-3 pr-3">
                    <div className="flex flex-col gap-1">
                      {(item.indicators ?? []).slice(0, 2).map((ind: string, i: number) => (
                        <span key={i} className="text-xs text-slate-400 flex items-center gap-1">
                          <span className="text-amber-400">•</span>
                          {ind.replace("XGBoost fraud classifier", "ML model: anomalous behaviour pattern")
                             .replace("Isolation Forest", "Statistical outlier")}
                        </span>
                      ))}
                      {(item.indicators?.length ?? 0) > 2 && (
                        <span className="text-xs text-slate-500">+{(item.indicators?.length ?? 0) - 2} more signals</span>
                      )}
                    </div>
                    <AIExplanationPanel accountId={item.account_id} />
                  </td>
                  <td className="py-3 pr-3 text-xs text-slate-300">
                    {formatINR(item.total_amount)}
                  </td>
                  <td className="py-3 text-xs text-slate-400">{item.branch_city}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-800">
            <span className="text-[10px] text-slate-500">{filtered.length} items · Page {queuePage + 1} of {totalPages}</span>
            <div className="flex items-center gap-1">
              <button onClick={() => setQueuePage(Math.max(0, queuePage - 1))} disabled={queuePage === 0} className="px-2 py-1 text-xs bg-slate-800 text-slate-400 rounded disabled:opacity-30 hover:text-white">←</button>
              <span className="text-[10px] text-slate-500 px-2">{queuePage + 1} / {totalPages}</span>
              <button onClick={() => setQueuePage(Math.min(totalPages - 1, queuePage + 1))} disabled={queuePage >= totalPages - 1} className="px-2 py-1 text-xs bg-slate-800 text-slate-400 rounded disabled:opacity-30 hover:text-white">→</button>
            </div>
          </div>
        )}
            </>
          );
        })()}
      </Card>

      {/* Speed Alerts */}
      <div>
        <h3 className="text-sm font-semibold text-slate-300 mb-4">Speed Alerts<InfoTooltip text="Transaction chains where funds moved across 3+ accounts faster than normal settlement time. FAST=<4h, VERY_FAST=<1h, ABNORMAL=<15min. Indicates potential automated layering." /></h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {speedAlerts.map((alert, idx) => (
            <div
              key={idx}
              className={`rounded-xl border p-4 ${speedCategoryColor(alert.category)}`}
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-bold text-slate-200 uppercase tracking-wider">
                  {alert.label}
                </span>
                <Badge
                  variant={
                    alert.category === "ABNORMAL"
                      ? "danger"
                      : alert.category === "VERY_FAST"
                      ? "warning"
                      : "info"
                  }
                >
                  {alert.category}
                </Badge>
              </div>
              <div className="space-y-1.5 text-xs text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-400">Avg min/hop</span>
                  <span className="font-medium">{alert.avg_minutes_per_hop.toFixed(1)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Total Amount</span>
                  <span className="font-medium">{formatINR(alert.total_amount)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Hops</span>
                  <span className="font-medium">{alert.hops}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Accounts</span>
                  <span className="font-medium">{alert.accounts.length}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
