"use client";

import React, { useEffect, useState } from "react";
import { api, ChannelData } from "@/lib/api";
import { Card, StatCard, Loader, Badge, FilterBar, FilterOption, InfoTooltip } from "@/components/ui";
import { formatINR } from "@/lib/utils";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

type SortKey = "channel" | "count" | "total_amount" | "avg_amount" | "max_amount";
type SortDir = "asc" | "desc";

const CHANNEL_COLORS: Record<string, string> = {
  UPI: "#8b5cf6",
  NEFT: "#3b82f6",
  RTGS: "#06b6d4",
  IMPS: "#10b981",
  CASH: "#f59e0b",
  CHEQUE: "#f97316",
  WIRE: "#ef4444",
  SWIFT: "#ec4899",
};

const CHANNEL_FILTERS: FilterOption[] = [
  { key: "channel", label: "Channel", type: "text", placeholder: "Filter channel..." },
  { key: "minAmount", label: "Min Total Amount", type: "number", placeholder: "Min ₹" },
  { key: "maxAmount", label: "Max Total Amount", type: "number", placeholder: "Max ₹" },
  { key: "minCount", label: "Min Txn Count", type: "number", placeholder: "Min count" },
];

function getChannelColor(channel: string): string {
  return CHANNEL_COLORS[channel.toUpperCase()] || "#6b7280";
}

export default function ChannelsPage() {
  const [data, setData] = useState<ChannelData | null>(null);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("total_amount");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [filterValues, setFilterValues] = useState<Record<string, string>>({});

  useEffect(() => {
    api.getChannels().then(setData).finally(() => setLoading(false));
  }, []);

  const handleFilterChange = (key: string, value: string) => {
    setFilterValues((prev) => ({ ...prev, [key]: value }));
  };
  const handleFilterReset = () => setFilterValues({});

  if (loading) return <Loader />;
  if (!data) return <div className="text-slate-400 text-center py-20">Failed to load channel data</div>;

  const summary = data.summary || [];
  const sankey = data.sankey || [];
  const heatmap = data.heatmap || [];
  const suspicious = data.suspicious || [];

  // Stats
  const totalChannels = summary.length;
  const mostUsed = summary.length > 0 ? summary.reduce((a, b) => (b.count > a.count ? b : a), summary[0]) : null;
  const suspiciousCount = suspicious.length;

  // Sorting
  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  // Filter and sort summary
  const filteredSummary = summary.filter((row) => {
    if (filterValues.channel && !row.channel.toLowerCase().includes(filterValues.channel.toLowerCase())) return false;
    if (filterValues.minAmount && row.total_amount < Number(filterValues.minAmount)) return false;
    if (filterValues.maxAmount && row.total_amount > Number(filterValues.maxAmount)) return false;
    if (filterValues.minCount && row.count < Number(filterValues.minCount)) return false;
    return true;
  });

  const sortedSummary = [...filteredSummary].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (typeof av === "string" && typeof bv === "string") {
      return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  const maxCount = Math.max(...summary.map((s) => s.count));

  // Heatmap: build grid
  const channels = [...new Set(heatmap.map((h) => h.channel))];
  const hours = Array.from({ length: 24 }, (_, i) => i);
  const heatmapMax = Math.max(...heatmap.map((h) => h.count), 1);

  const getHeatmapValue = (channel: string, hour: number) => {
    const entry = heatmap.find((h) => h.channel === channel && h.hour === hour);
    return entry?.count || 0;
  };

  // Top flows from sankey data
  const topFlows = [...sankey].sort((a, b) => b.total - a.total).slice(0, 20);

  // Channel flow chart data
  const flowByChannel: Record<string, { channel: string; count: number; total: number }> = {};
  sankey.forEach((f) => {
    if (!flowByChannel[f.channel]) {
      flowByChannel[f.channel] = { channel: f.channel, count: 0, total: 0 };
    }
    flowByChannel[f.channel].count += f.count;
    flowByChannel[f.channel].total += f.total;
  });
  const flowChartData = Object.values(flowByChannel).sort((a, b) => b.total - a.total);

  return (
    <div className="space-y-6 p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Channel Analytics <InfoTooltip text="Channel Analytics shows how transactions are distributed across payment channels (NEFT, RTGS, IMPS, UPI, Cash, etc.). Unusual channel patterns — like a business account using only cash — can indicate attempts to avoid digital audit trails." /></h1>
        <p className="text-sm text-slate-400 mt-1">
          Transaction channel usage patterns and anomalies
        </p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="Total Channels" value={totalChannels} icon="📡" color="blue" />
        <StatCard
          label="Most Used Channel"
          value={mostUsed?.channel || "N/A"}
          sub={mostUsed ? `${mostUsed.count.toLocaleString()} txns` : ""}
          icon="🏆"
          color="green"
        />
        <StatCard label="Suspicious Channels" value={suspiciousCount} icon="🚨" color="red" />
      </div>

      {/* Channel Summary Table */}
      <FilterBar filters={CHANNEL_FILTERS} values={filterValues} onChange={handleFilterChange} onReset={handleFilterReset} />
      <Card>
        <h2 className="text-lg font-semibold text-white mb-4">Channel Summary ({filteredSummary.length} of {summary.length})</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 text-slate-400 text-xs uppercase">
                {([
                  { key: "channel" as SortKey, label: "Channel" },
                  { key: "count" as SortKey, label: <>Transaction Count <InfoTooltip text="Number of transactions using this channel in the loaded dataset period." /></> },
                  { key: "total_amount" as SortKey, label: <>Total Amount <InfoTooltip text="Cumulative rupee value of all transactions through this channel. Large totals through informal channels like cash warrant scrutiny." /></> },
                  { key: "avg_amount" as SortKey, label: <>Avg Amount <InfoTooltip text="Average transaction size on this channel. Structuring attacks often show average amounts clustered just below reporting thresholds (e.g. ₹9.5L average on a ₹10L threshold channel)." /></> },
                  { key: "max_amount" as SortKey, label: "Max Amount" },
                ] as { key: SortKey; label: React.ReactNode }[]).map((col) => (
                  <th
                    key={col.key}
                    className={`py-3 px-2 cursor-pointer hover:text-white transition-colors ${col.key === "channel" ? "text-left" : "text-right"}`}
                    onClick={() => handleSort(col.key)}
                  >
                    {col.label} {sortKey === col.key ? (sortDir === "desc" ? "↓" : "↑") : ""}
                  </th>
                ))}
                <th className="py-3 px-2 text-left">Volume</th>
              </tr>
            </thead>
            <tbody>
              {sortedSummary.map((row) => (
                <tr key={row.channel} className="border-b border-slate-800 hover:bg-slate-800/50">
                  <td className="py-2 px-2">
                    <span
                      className="inline-block w-2 h-2 rounded-full mr-2"
                      style={{ backgroundColor: getChannelColor(row.channel) }}
                    />
                    <span className="text-white font-medium">{row.channel}</span>
                  </td>
                  <td className="py-2 px-2 text-right text-slate-300">
                    {row.count.toLocaleString()}
                  </td>
                  <td className="py-2 px-2 text-right text-slate-300">
                    {formatINR(row.total_amount)}
                  </td>
                  <td className="py-2 px-2 text-right text-slate-300">
                    {formatINR(row.avg_amount)}
                  </td>
                  <td className="py-2 px-2 text-right text-slate-300">
                    {formatINR(row.max_amount)}
                  </td>
                  <td className="py-2 px-2 w-32">
                    <div className="w-full bg-slate-700 rounded-full h-2">
                      <div
                        className="h-2 rounded-full"
                        style={{
                          width: `${(row.count / maxCount) * 100}%`,
                          backgroundColor: getChannelColor(row.channel),
                        }}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Channel Flow Visualization */}
      <Card>
        <h2 className="text-lg font-semibold text-white mb-4">Channel Flow Volume <InfoTooltip text="Sankey diagram shows how funds flow from source account types through payment channels to destination account types. Wide flows between unusual account type pairs (e.g. individual → corporate via cash) are worth investigating." /></h2>
        <div className="h-[300px] mb-6">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={flowChartData} margin={{ top: 10, right: 20, bottom: 20, left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis
                dataKey="channel"
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                axisLine={{ stroke: "#475569" }}
              />
              <YAxis
                tick={{ fill: "#94a3b8", fontSize: 11 }}
                tickFormatter={(v) => formatINR(v)}
                axisLine={{ stroke: "#475569" }}
              />
              <Tooltip
                contentStyle={{ backgroundColor: "#1e293b", border: "1px solid #475569", borderRadius: 8 }}
                labelStyle={{ color: "#e2e8f0" }}
                formatter={(value) => [formatINR(Number(value)), "Total Amount"]}
              />
              <Bar dataKey="total" radius={[4, 4, 0, 0]} fill="#3b82f6" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <h3 className="text-sm font-medium text-slate-300 mb-3">Top 20 Transaction Flows</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {topFlows.map((flow, i) => (
            <div
              key={i}
              className="flex items-center gap-3 bg-slate-800/50 rounded-lg px-3 py-2 border border-slate-700/50"
            >
              <div
                className="w-1 h-8 rounded-full"
                style={{ backgroundColor: getChannelColor(flow.channel) }}
              />
              <div className="flex-1 min-w-0">
                <p className="text-xs text-white truncate">
                  <span className="text-slate-400">{flow.source_type}</span>
                  {" → "}
                  <span className="font-medium" style={{ color: getChannelColor(flow.channel) }}>
                    {flow.channel}
                  </span>
                  {" → "}
                  <span className="text-slate-400">{flow.dest_type}</span>
                </p>
                <p className="text-[10px] text-slate-500">
                  {flow.count} txns · {formatINR(flow.total)}
                </p>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Activity Heatmap */}
      <Card>
        <h2 className="text-lg font-semibold text-white mb-4">Activity Heatmap <InfoTooltip text="This heatmap shows transaction frequency by channel and hour of day. Legitimate businesses show predictable patterns. Money launderers often transact at unusual hours to exploit reduced monitoring." /></h2>
        <p className="text-xs text-slate-400 mb-4">Transaction count by channel and hour of day</p>
        <div className="overflow-x-auto">
          <div className="min-w-[700px]">
            {/* Hour labels */}
            <div className="flex items-center mb-1">
              <div className="w-20 flex-shrink-0" />
              <div className="flex-1 flex">
                {hours.map((h) => (
                  <div key={h} className="flex-1 text-center text-[9px] text-slate-500">
                    {h}
                  </div>
                ))}
              </div>
            </div>
            {/* Rows */}
            {channels.map((channel) => (
              <div key={channel} className="flex items-center mb-[2px]">
                <div className="w-20 flex-shrink-0 text-xs text-slate-400 truncate pr-2">
                  {channel}
                </div>
                <div className="flex-1 flex gap-[1px]">
                  {hours.map((hour) => {
                    const value = getHeatmapValue(channel, hour);
                    const intensity = value / heatmapMax;
                    return (
                      <div
                        key={hour}
                        className="flex-1 h-6 rounded-sm cursor-pointer relative group"
                        style={{
                          backgroundColor: `rgba(59, 130, 246, ${Math.max(intensity * 0.9, 0.05)})`,
                        }}
                        title={`${channel} @ ${hour}:00 — ${value} txns`}
                      >
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1 hidden group-hover:block z-10">
                          <div className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-[10px] text-white whitespace-nowrap">
                            {value} txns
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
            {/* Legend */}
            <div className="flex items-center justify-end mt-3 gap-2">
              <span className="text-[10px] text-slate-500">Low</span>
              <div className="flex gap-[1px]">
                {[0.1, 0.3, 0.5, 0.7, 0.9].map((v) => (
                  <div
                    key={v}
                    className="w-4 h-3 rounded-sm"
                    style={{ backgroundColor: `rgba(59, 130, 246, ${v})` }}
                  />
                ))}
              </div>
              <span className="text-[10px] text-slate-500">High</span>
            </div>
          </div>
        </div>
      </Card>

      {/* Suspicious Channel Usage */}
      <Card>
        <h2 className="text-lg font-semibold text-white mb-4">
          Suspicious Channel Usage <InfoTooltip text="Channels are flagged as suspicious when their transaction patterns deviate significantly from expected norms — e.g. unusually high cash volumes, off-hours NEFT transfers, or channels used exclusively by high-risk accounts." />
        </h2>
        {suspicious.length === 0 ? (
          <p className="text-slate-500 text-sm">No suspicious channel activity detected</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-slate-400 text-xs uppercase">
                  <th className="text-left py-3 px-2">Channel</th>
                  <th className="text-right py-3 px-2">Count</th>
                  <th className="text-right py-3 px-2">Total Amount</th>
                  <th className="text-right py-3 px-2">Unique Accounts</th>
                  <th className="text-center py-3 px-2">Risk</th>
                </tr>
              </thead>
              <tbody>
                {suspicious.map((row) => (
                  <tr key={row.channel} className="border-b border-slate-800 hover:bg-red-500/5">
                    <td className="py-2 px-2">
                      <span
                        className="inline-block w-2 h-2 rounded-full mr-2"
                        style={{ backgroundColor: getChannelColor(row.channel) }}
                      />
                      <span className="text-white font-medium">{row.channel}</span>
                    </td>
                    <td className="py-2 px-2 text-right text-slate-300">
                      {row.count.toLocaleString()}
                    </td>
                    <td className="py-2 px-2 text-right text-slate-300">
                      {formatINR(row.total)}
                    </td>
                    <td className="py-2 px-2 text-right text-slate-300">
                      {row.unique_accounts}
                    </td>
                    <td className="py-2 px-2 text-center">
                      <Badge variant="danger">⚠️ Suspicious</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
