"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { api, OverviewData, DashboardLive, DailySummary } from "@/lib/api";
import { Card, StatCard, Loader, SkeletonCard, InfoTooltip } from "@/components/ui";
import { formatINR, getRiskBg, getRiskDot, getRoleIcon } from "@/lib/utils";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
  CartesianGrid,
} from "recharts";

const RISK_COLORS: Record<string, string> = {
  CRITICAL: "#ef4444",
  HIGH: "#f97316",
  MEDIUM: "#eab308",
  LOW: "#22c55e",
};

const ROLE_COLORS: Record<string, string> = {
  MULE: "#eab308",
  SOURCE: "#ef4444",
  SINK: "#8b5cf6",
  NORMAL: "#6b7280",
};

function riskLevelForScore(score: number): string {
  if (score > 80) return "CRITICAL";
  if (score > 60) return "HIGH";
  if (score > 40) return "MEDIUM";
  return "LOW";
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-700 bg-[#1e293b] px-3 py-2 text-xs text-white shadow-lg">
      {label && <p className="mb-1 font-medium text-slate-300">{label}</p>}
      {payload.map((p: any, i: number) => (
        <p key={i} style={{ color: p.color }}>
          {p.name}: {typeof p.value === "number" ? p.value.toLocaleString() : p.value}
        </p>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState<OverviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedSection, setExpandedSection] = useState<string | null>(null);
  const [alertPage, setAlertPage] = useState(0);
  const [alertFilter, setAlertFilter] = useState<string>("ALL");
  const [notInitialized, setNotInitialized] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [liveData, setLiveData] = useState<DashboardLive | null>(null);
  const [dailySummary, setDailySummary] = useState<DailySummary | null>(null);
  const [todaysActivityExpanded, setTodaysActivityExpanded] = useState<"new" | "reactivated" | null>(null);
  const ALERTS_PER_PAGE = 10;

  const loadDashboard = () => {
    api
      .getOverview()
      .then((d) => { setData(d); setNotInitialized(false); })
      .catch((err) => {
        if (err?.message?.includes("503") || err?.message?.includes("not initialized")) {
          setNotInitialized(true);
        }
      })
      .finally(() => { setLoading(false); setRefreshing(false); });
    api.getDailySummary().then(setDailySummary).catch(() => setDailySummary(null));
  };

  useEffect(() => {
    loadDashboard();
    // Auto-refresh when tab becomes visible (user navigated back from ingest page)
    const onVisibility = () => { if (document.visibilityState === "visible") loadDashboard(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  // Poll the live system activity panel independently of the main overview fetch.
  useEffect(() => {
    const loadLive = () => {
      api
        .getDashboardLive()
        .then((d) => setLiveData(d))
        .catch((err) => console.warn("Failed to fetch live dashboard data", err));
    };
    loadLive();
    const interval = setInterval(loadLive, 3000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => { setRefreshing(true); loadDashboard(); };

  if (loading) return (
    <div className="min-h-screen bg-[#0b1120] p-6 text-white max-w-[1600px] mx-auto">
      <div className="mb-6">
        <div className="h-7 w-40 bg-slate-800 rounded animate-pulse" />
        <div className="h-3 w-64 bg-slate-800/50 rounded mt-2 animate-pulse" />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
        {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="h-64 bg-slate-800/30 rounded-xl border border-slate-700/30 animate-pulse" />
        <div className="h-64 bg-slate-800/30 rounded-xl border border-slate-700/30 animate-pulse" />
      </div>
    </div>
  );
  if (!data) {
    if (notInitialized) {
      return (
        <div className="min-h-screen bg-[#0b1120] flex items-center justify-center">
          <div className="text-center max-w-md">
            <div className="text-5xl mb-4">📊</div>
            <h2 className="text-xl font-semibold text-white mb-2">No Data Loaded</h2>
            <p className="text-slate-400 text-sm mb-6">
              Upload transaction data to get started with AML analysis. The system will automatically detect patterns, score risks, and build the transaction graph.
            </p>
            <Link
              href="/ingest"
              className="inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg transition font-medium"
            >
              Upload Data →
            </Link>
          </div>
        </div>
      );
    }
    return <p className="text-center text-slate-400 py-20">Failed to load data</p>;
  }

  const riskData = Object.entries(data.risk_distribution).map(([name, value]) => ({ name, value }));
  const roleData = Object.entries(data.role_distribution).map(([name, value]) => ({ name, value }));
  const patternData = Object.entries(data.pattern_counts).map(([name, value]) => ({ name, value }));

  const filteredAlerts = alertFilter === "ALL"
    ? data.top_alerts
    : data.top_alerts.filter((a) => a.risk_level === alertFilter);
  const totalAlertPages = Math.ceil(filteredAlerts.length / ALERTS_PER_PAGE);
  const pagedAlerts = filteredAlerts.slice(alertPage * ALERTS_PER_PAGE, (alertPage + 1) * ALERTS_PER_PAGE);

  const toggleSection = (key: string) => setExpandedSection(expandedSection === key ? null : key);

  return (
    <div className="min-h-screen bg-[#0b1120] p-6 text-white max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">AML Dashboard</h1>
          <p className="text-xs text-slate-400">Real-time anti-money laundering monitoring</p>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 rounded-lg transition text-xs"
          >
            {refreshing ? "Refreshing..." : "↻ Refresh"}
          </button>
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          Live
        </div>
      </div>

      {/* Live System Activity */}
      <Card className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Live System Activity</h3>
          <div className="flex items-center gap-1.5 text-xs text-slate-500">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            Live
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-slate-500 text-xs block">Transactions (60s)</span>
            <span className="text-white font-medium text-lg">{liveData ? liveData.transactions_last_60s.toLocaleString() : "—"}</span>
          </div>
          <div>
            <span className="text-slate-500 text-xs block">Alerts (60s)</span>
            <span className="text-white font-medium text-lg">{liveData ? liveData.alerts_last_60s.toLocaleString() : "—"}</span>
          </div>
          <div>
            <span className="text-slate-500 text-xs block">Highest Risk Today</span>
            {liveData?.highest_risk_account_today ? (
              <div className="flex items-center gap-2 mt-0.5">
                <span className="font-mono text-xs text-blue-400">{liveData.highest_risk_account_today.account_id}</span>
                <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${getRiskBg(riskLevelForScore(liveData.highest_risk_account_today.score))}`}>
                  <span className={`h-1.5 w-1.5 rounded-full ${getRiskDot(riskLevelForScore(liveData.highest_risk_account_today.score))}`} />
                  {liveData.highest_risk_account_today.score.toFixed(1)}
                </span>
              </div>
            ) : (
              <span className="text-white font-medium text-lg">{liveData ? "No data yet" : "—"}</span>
            )}
          </div>
          <div>
            <span className="text-slate-500 text-xs block">Event Bus Queue Depth</span>
            <span className="text-white font-medium text-lg">{liveData ? liveData.event_bus_queue_depth.toLocaleString() : "—"}</span>
            {liveData && (
              <span className="text-slate-500 text-[10px] block mt-0.5">{liveData.event_bus_queue_depth} pending · {liveData.dlq_depth} DLQ</span>
            )}
          </div>
        </div>
      </Card>

      {/* Today's Activity — distinguishes patterns flagged for the first time
          today from ones still active/re-detected on the latest pipeline run */}
      {dailySummary && (
        <Card className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Today's Activity <InfoTooltip text="New Today = patterns detected for the first time on the most recent pipeline run. Reactivated = still-active alerts whose pattern was detected again (not a new finding)." />
            </h3>
            <span className="text-[10px] text-slate-500">as of {new Date(dailySummary.run_at).toLocaleTimeString()}</span>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <button
              onClick={() => setTodaysActivityExpanded(todaysActivityExpanded === "new" ? null : "new")}
              className="text-left rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3 hover:bg-emerald-500/10 transition"
            >
              <span className="text-slate-400 text-xs block">🆕 New Today</span>
              <span className="text-emerald-400 font-bold text-xl">{dailySummary.new_alerts.length}</span>
            </button>
            <button
              onClick={() => setTodaysActivityExpanded(todaysActivityExpanded === "reactivated" ? null : "reactivated")}
              className="text-left rounded-lg border border-slate-700 bg-slate-800/40 p-3 hover:bg-slate-800/70 transition"
            >
              <span className="text-slate-400 text-xs block">🔁 Reactivated</span>
              <span className="text-slate-300 font-bold text-xl">{dailySummary.reactivated_alerts.length}</span>
            </button>
          </div>
          {todaysActivityExpanded && (
            <div className="mt-3 pt-3 border-t border-slate-800 space-y-1.5 max-h-56 overflow-y-auto">
              {(todaysActivityExpanded === "new" ? dailySummary.new_alerts : dailySummary.reactivated_alerts).map((a) => (
                <div key={a.alert_id} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${getRiskBg(a.severity)}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${getRiskDot(a.severity)}`} />
                      {a.severity}
                    </span>
                    <span className="text-slate-300">{a.pattern_type.replace(/_/g, " ")}</span>
                  </div>
                  <Link href={`/graph?account=${a.account_id}`} className="font-mono text-blue-400 hover:text-blue-300">
                    {a.account_id} →
                  </Link>
                </div>
              ))}
              {(todaysActivityExpanded === "new" ? dailySummary.new_alerts : dailySummary.reactivated_alerts).length === 0 && (
                <p className="text-slate-600 text-xs">None</p>
              )}
            </div>
          )}
        </Card>
      )}

      {/* Stat Cards - Clickable to Expand */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
        <button onClick={() => toggleSection("accounts")} className="text-left">
          <StatCard label="Accounts" value={data.stats.num_nodes.toLocaleString()} icon="👥" color="blue" />
        </button>
        <button onClick={() => toggleSection("transactions")} className="text-left">
          <StatCard label="Transactions" value={data.stats.num_edges.toLocaleString()} icon="💳" color="purple" />
        </button>
        <button onClick={() => toggleSection("flagged")} className="text-left">
          <StatCard
            label={<>Flagged <InfoTooltip text="Count of accounts flagged by at least one AML detector or ML model score above threshold. Does not mean confirmed fraud — requires investigator review." /></>}
            value={data.total_flagged.toLocaleString()}
            icon="🚨"
            color="red"
          />
        </button>
        <button onClick={() => toggleSection("anomalies")} className="text-left">
          <StatCard label="Anomalies" value={data.total_anomalies.toLocaleString()} icon="⚠️" color="orange" />
        </button>
        <button onClick={() => toggleSection("risk")} className="text-left">
          <StatCard label="Critical Alerts" value={(data.risk_distribution["CRITICAL"] ?? 0).toString()} icon="🔴" color="red" />
        </button>
        <button onClick={() => toggleSection("volume")} className="text-left">
          <StatCard label={<>Total Volume <InfoTooltip text="Total rupee value of all transactions in the loaded dataset. This represents the financial exposure being monitored in the current analysis window." /></>} value={formatINR(data.total_amount)} icon="💰" color="green" />
        </button>
      </div>

      {/* Expanded Detail Panel */}
      {expandedSection && expandedSection !== "model" && (
        <Card className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-300">
              {expandedSection === "accounts" && "Network Details"}
              {expandedSection === "transactions" && "Transaction Details"}
              {expandedSection === "flagged" && "Flagged Accounts Breakdown"}
              {expandedSection === "anomalies" && "Anomaly Detection Details"}
              {expandedSection === "risk" && "Risk Score Distribution"}
              {expandedSection === "volume" && "Volume Analysis"}
            </h3>
            <button onClick={() => setExpandedSection(null)} className="text-slate-500 hover:text-white text-sm">✕</button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            {expandedSection === "accounts" && (
              <>
                <div><span className="text-slate-500 text-xs block">Nodes</span><span className="text-white font-medium">{data.stats.num_nodes}</span></div>
                <div><span className="text-slate-500 text-xs block">Components</span><span className="text-white font-medium">{data.stats.num_components}</span></div>
                <div><span className="text-slate-500 text-xs block">Density <InfoTooltip text="Graph density measures the proportion of possible connections that actually exist. Very dense subgraphs (high density among high-risk accounts) indicate a tightly coordinated network — a stronger indicator of organised financial crime than isolated high-risk accounts." /></span><span className="text-white font-medium">{data.stats.density.toFixed(4)}</span></div>
                <div><span className="text-slate-500 text-xs block">Avg In-Degree</span><span className="text-white font-medium">{data.stats.avg_in_degree.toFixed(2)}</span></div>
              </>
            )}
            {expandedSection === "transactions" && (
              <>
                <div><span className="text-slate-500 text-xs block">Total Edges</span><span className="text-white font-medium">{data.stats.num_edges}</span></div>
                <div><span className="text-slate-500 text-xs block">Avg Out-Degree</span><span className="text-white font-medium">{data.stats.avg_out_degree.toFixed(2)}</span></div>
                <div><span className="text-slate-500 text-xs block">Total Volume</span><span className="text-white font-medium">{formatINR(data.total_amount)}</span></div>
                <div><span className="text-slate-500 text-xs block">Avg per Txn</span><span className="text-white font-medium">{formatINR(data.total_amount / Math.max(data.stats.num_edges, 1))}</span></div>
              </>
            )}
            {expandedSection === "flagged" && Object.entries(data.risk_distribution).map(([level, count]) => (
              <div key={level}><span className="text-slate-500 text-xs block">{level}</span><span className="font-medium" style={{ color: RISK_COLORS[level] }}>{count}</span></div>
            ))}
            {expandedSection === "anomalies" && (
              <>
                <div><span className="text-slate-500 text-xs block">Anomalies</span><span className="text-orange-400 font-medium">{data.total_anomalies}</span></div>
                <div><span className="text-slate-500 text-xs block">Normal</span><span className="text-green-400 font-medium">{data.stats.num_nodes - data.total_anomalies}</span></div>
                <div><span className="text-slate-500 text-xs block">Rate</span><span className="text-white font-medium">{((data.total_anomalies / Math.max(data.stats.num_nodes, 1)) * 100).toFixed(1)}%</span></div>
                <div><Link href="/anomaly" className="text-blue-400 hover:text-blue-300 text-xs">View Details →</Link></div>
              </>
            )}
            {expandedSection === "risk" && Object.entries(data.risk_distribution).map(([level, count]) => (
              <div key={level} className="flex items-center gap-2">
                <div className="h-3 w-3 rounded-full" style={{ backgroundColor: RISK_COLORS[level] }} />
                <div><span className="text-xs text-slate-400">{level}</span><span className="block text-white font-medium">{count} ({((count / Math.max(data.stats.num_nodes, 1)) * 100).toFixed(0)}%)</span></div>
              </div>
            ))}
            {expandedSection === "volume" && (
              <>
                <div><span className="text-slate-500 text-xs block">Total Volume</span><span className="text-green-400 font-medium">{formatINR(data.total_amount)}</span></div>
                <div><span className="text-slate-500 text-xs block">Per Transaction</span><span className="text-white font-medium">{formatINR(data.total_amount / Math.max(data.stats.num_edges, 1))}</span></div>
                <div><span className="text-slate-500 text-xs block">Per Account</span><span className="text-white font-medium">{formatINR(data.total_amount / Math.max(data.stats.num_nodes, 1))}</span></div>
                <div><Link href="/channels" className="text-blue-400 hover:text-blue-300 text-xs">Channel Breakdown →</Link></div>
              </>
            )}
          </div>
        </Card>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <Card>
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Risk Distribution<InfoTooltip text="Accounts scored 0–100 by XGBoost ML model + Isolation Forest. CRITICAL >80, HIGH 60–80, MEDIUM 40–60, LOW <40. Score combines ML probability, rule detector hits, and graph centrality." /></h3>
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={riskData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" nameKey="name" paddingAngle={2}>
                {riskData.map((entry) => (
                  <Cell key={entry.name} fill={RISK_COLORS[entry.name] || "#6b7280"} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: "11px" }} iconType="circle" />
            </PieChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Role Distribution <InfoTooltip text="Network roles assigned by graph analysis: SOURCE = originator of funds, SINK = terminal recipient, MULE = passes funds through rapidly, NORMAL = expected transaction behaviour. Role distribution shifts indicate changing network structure." /></h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={roleData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="name" tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <YAxis tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="value" name="Accounts" radius={[4, 4, 0, 0]}>
                {roleData.map((entry) => (
                  <Cell key={entry.name} fill={ROLE_COLORS[entry.name] || "#6b7280"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card>
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Patterns Detected<InfoTooltip text="AML typologies detected by rule-based detectors. Layering: funds moved through ≥3 hops to obscure source. Round-trip: funds return to origin. Structuring: deposits just below reporting threshold (₹10L). Fan-out: one account distributes to many." /></h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={patternData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 11 }} />
              <YAxis type="category" dataKey="name" tick={{ fill: "#94a3b8", fontSize: 10 }} width={110} />
              <Tooltip content={<CustomTooltip />} />
              <Bar dataKey="value" name="Count" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* Alerts Table */}
      <Card className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Top Alerts<InfoTooltip text="Accounts with highest combined risk across ML model, AML rule detectors, and network centrality. Patterns column shows which typologies were detected for that account." /></h3>
          <div className="flex items-center gap-1.5">
            {["ALL", "CRITICAL", "HIGH", "MEDIUM", "LOW"].map((level) => (
              <button
                key={level}
                onClick={() => { setAlertFilter(level); setAlertPage(0); }}
                className={`px-2 py-1 text-[10px] rounded-full font-medium transition ${
                  alertFilter === level ? "bg-blue-600 text-white" : "bg-slate-800 text-slate-400 hover:text-white"
                }`}
              >
                {level}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 text-left text-[10px] text-slate-500 uppercase tracking-wider">
                <th className="pb-2 pr-4">Account</th>
                <th className="pb-2 pr-4">Risk</th>
                <th className="pb-2 pr-4">Level</th>
                <th className="pb-2 pr-4">Role</th>
                <th className="pb-2 pr-4">Patterns</th>
                <th className="pb-2 pr-4">Branch</th>
                <th className="pb-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {pagedAlerts.map((alert) => (
                <tr key={alert.account_id} className="border-b border-slate-800/50 hover:bg-slate-800/30 transition">
                  <td className="py-2.5 pr-4 font-mono text-xs text-blue-400">{alert.account_id}</td>
                  <td className="py-2.5 pr-4">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 rounded-full bg-slate-700 overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.min(alert.risk_score, 100)}%`, backgroundColor: RISK_COLORS[alert.risk_level] || "#6b7280" }} />
                      </div>
                      <span className="text-[10px] text-slate-400 w-8">{alert.risk_score.toFixed(0)}</span>
                    </div>
                  </td>
                  <td className="py-2.5 pr-4">
                    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium ${getRiskBg(alert.risk_level)}`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${getRiskDot(alert.risk_level)}`} />
                      {alert.risk_level}
                    </span>
                  </td>
                  <td className="py-2.5 pr-4 text-xs text-slate-300">{getRoleIcon(alert.role)} {alert.role}</td>
                  <td className="py-2.5 pr-4">
                    <div className="flex flex-wrap gap-1">
                      {((alert as any).patterns ?? (alert as any).detection_types ?? []).slice(0, 2).map((p: string) => (
                        <span key={p} className="text-[9px] bg-slate-700 text-slate-300 px-1.5 py-0.5 rounded">
                          {p.replace(/_/g, " ")}
                        </span>
                      ))}
                      {((alert as any).patterns ?? (alert as any).detection_types ?? []).length === 0 && (
                        <span className="text-[10px] text-slate-600">—</span>
                      )}
                    </div>
                  </td>
                  <td className="py-2.5 pr-4 text-xs text-slate-500">{alert.branch_city}</td>
                  <td className="py-2.5">
                    <Link href={`/graph?account=${alert.account_id}`} className="text-[10px] text-blue-400 hover:text-blue-300">Investigate →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {totalAlertPages > 1 && (
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-800">
            <span className="text-[10px] text-slate-500">{filteredAlerts.length} alerts</span>
            <div className="flex items-center gap-1">
              <button onClick={() => setAlertPage(Math.max(0, alertPage - 1))} disabled={alertPage === 0} className="px-2 py-1 text-xs bg-slate-800 text-slate-400 rounded disabled:opacity-30 hover:text-white">←</button>
              <span className="text-[10px] text-slate-500 px-2">{alertPage + 1} / {totalAlertPages}</span>
              <button onClick={() => setAlertPage(Math.min(totalAlertPages - 1, alertPage + 1))} disabled={alertPage >= totalAlertPages - 1} className="px-2 py-1 text-xs bg-slate-800 text-slate-400 rounded disabled:opacity-30 hover:text-white">→</button>
            </div>
          </div>
        )}
      </Card>

      {/* Action Required — replaces ML model metrics panel which is not meaningful to compliance officers */}
      <div className="bg-slate-800 border border-amber-500/30 rounded-xl p-6">
        <h3 className="text-base font-semibold text-amber-400 mb-4">Action Required</h3>
        <div className="grid grid-cols-3 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-red-400">{data.risk_distribution["CRITICAL"] ?? 0}</div>
            <div className="text-xs text-slate-400 mt-1">Critical Alerts</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-amber-400">{data.risk_distribution["HIGH"] ?? 0}</div>
            <div className="text-xs text-slate-400 mt-1">High Risk Accounts</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-slate-300">{data.total_flagged}</div>
            <div className="text-xs text-slate-400 mt-1">Accounts Flagged</div>
          </div>
        </div>
        <div className="mt-4 pt-4 border-t border-slate-700/50 flex items-center justify-between">
          <p className="text-xs text-slate-500">Review all flagged accounts in the investigation queue before filing STR reports.</p>
          <Link href="/anomaly" className="text-xs text-blue-400 hover:text-blue-300 whitespace-nowrap">Open Queue →</Link>
        </div>
      </div>
    </div>
  );
}
