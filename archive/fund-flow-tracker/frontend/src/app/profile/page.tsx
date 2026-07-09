"use client";

import { useEffect, useState, type JSX } from "react";
import Link from "next/link";
import { api, ProfileData, AccountDetail } from "@/lib/api";
import { Card, StatCard, Loader, Badge, EmptyState, FilterBar, FilterOption, InfoTooltip } from "@/components/ui";
import { formatINR } from "@/lib/utils";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

interface PeerGroupResult {
  account_id: string;
  occupation: string;
  income_bracket: string;
  declared_income: number;
  actual_volume: number;
  peer_mean: number;
  peer_std: number;
  z_score: number;
  peer_count: number;
}

const PROFILE_FILTERS: FilterOption[] = [
  {
    key: "severity",
    label: "Severity",
    type: "select",
    options: [
      { value: "CRITICAL", label: "Critical (>10x)" },
      { value: "HIGH", label: "High (>5x)" },
      { value: "MEDIUM", label: "Medium (>2x)" },
      { value: "LOW", label: "Low (≤2x)" },
    ],
  },
  { key: "accountSearch", label: "Account ID", type: "text", placeholder: "Search account..." },
  { key: "occupation", label: "Occupation", type: "text", placeholder: "Occupation..." },
  { key: "minRatio", label: "Min Ratio", type: "number", placeholder: "Min ratio" },
];

function getSeverity(ratio: number): { label: string; variant: "danger" | "warning" | "info" | "success" } {
  if (ratio > 10) return { label: "CRITICAL", variant: "danger" };
  if (ratio > 5) return { label: "HIGH", variant: "warning" };
  if (ratio > 2) return { label: "MEDIUM", variant: "info" };
  return { label: "LOW", variant: "success" };
}

const RISK_COLORS: Record<string, string> = {
  CRITICAL: "#ef4444",
  HIGH: "#f97316",
  MEDIUM: "#eab308",
  LOW: "#22c55e",
};

const OCC_PALETTE = [
  "#3b82f6", "#8b5cf6", "#22c55e", "#f97316",
  "#eab308", "#06b6d4", "#ec4899", "#f43f5e",
  "#a855f7", "#14b8a6",
];

function getOccColor(occ: string, occupations: string[]): string {
  const idx = occupations.indexOf(occ);
  return OCC_PALETTE[Math.max(0, idx) % OCC_PALETTE.length];
}

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

export default function ProfilePage() {
  const [data, setData] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  // Standalone peer group lookup (existing feature)
  const [peerAccountId, setPeerAccountId] = useState("");
  const [peerData, setPeerData] = useState<PeerGroupResult | null>(null);
  const [peerLoading, setPeerLoading] = useState(false);
  // Mismatch table state
  const [mismatchPage, setMismatchPage] = useState(0);
  const [filterValues, setFilterValues] = useState<Record<string, string>>({});
  // Account detail drawer state
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [accountDetail, setAccountDetail] = useState<AccountDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [peerGroupForSelected, setPeerGroupForSelected] = useState<PeerGroupResult | null>(null);

  const MISMATCH_PER_PAGE = 15;

  useEffect(() => {
    api.getProfile().then(setData).finally(() => setLoading(false));
  }, []);

  const handleFilterChange = (key: string, value: string) => {
    setFilterValues((prev) => ({ ...prev, [key]: value }));
    setMismatchPage(0);
  };
  const handleFilterReset = () => { setFilterValues({}); setMismatchPage(0); };

  const handlePeerAnalysis = async () => {
    if (!peerAccountId.trim()) return;
    setPeerLoading(true);
    try {
      const result = await api.getPeerGroup(peerAccountId.trim());
      setPeerData(result as unknown as PeerGroupResult);
    } catch {
      setPeerData(null);
    } finally {
      setPeerLoading(false);
    }
  };

  const handleViewDetails = async (id: string) => {
    // Toggle off if same row clicked again
    if (selectedId === id) {
      setSelectedId(null);
      setAccountDetail(null);
      setPeerGroupForSelected(null);
      return;
    }
    setSelectedId(id);
    setAccountDetail(null);
    setPeerGroupForSelected(null);
    setDetailLoading(true);
    try {
      const [detail, peer] = await Promise.all([
        api.getAccountDetail(id),
        api.getPeerGroup(id).catch(() => null),
      ]);
      setAccountDetail(detail);
      setPeerGroupForSelected(peer as unknown as PeerGroupResult);
    } catch {
      setAccountDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  if (loading) return <Loader />;
  if (!data) return <EmptyState message="Failed to load profile data" />;

  const scatter_data = data.scatter_data || [];
  const mismatches = data.mismatches || [];
  const mismatchCount = mismatches.length;
  const avgRatio =
    scatter_data.length > 0
      ? (scatter_data.reduce((s, d) => s + (d.ratio || 0), 0) / scatter_data.length).toFixed(2)
      : "0";

  const sortedMismatches = [...mismatches].sort(
    (a, b) => ((b as Record<string, number>).ratio || 0) - ((a as Record<string, number>).ratio || 0)
  );

  // Derive unique occupations for color palette
  const occupations = [...new Set(scatter_data.map((d) => d.occupation))];

  // Enrich each scatter point with a pre-computed color field
  const coloredScatterData = scatter_data.map((d) => ({
    ...d,
    color: getOccColor(d.occupation, occupations),
  }));

  return (
    <div className="space-y-6 p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Profile Analyzer</h1>
        <p className="text-sm text-slate-400 mt-1">
          Profile Analyzer detects accounts whose actual transaction volumes significantly exceed their
          declared income or expected behavior for their occupation and income bracket.
        </p>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="Total Accounts" value={scatter_data.length} icon="👤" color="blue" />
        <StatCard label="Mismatches Detected" value={mismatchCount} icon="⚠️" color="red" />
        <StatCard label="Avg Volume/Income Ratio" value={avgRatio} icon="📊" color="purple" />
      </div>

      {/* Two-column layout: Scatter (60%) + Mismatch Table (40%) */}
      <div className="grid grid-cols-1 xl:grid-cols-5 gap-4 items-start">
        {/* Left panel — Scatter Plot */}
        <div className="xl:col-span-3">
          <Card>
            <h2 className="text-lg font-semibold text-white mb-2">Income vs Transaction Volume<InfoTooltip text="Each dot is an account. X-axis = declared annual income, Y-axis = actual total inflow. Dots above the diagonal line are transacting more than their declared income can explain. Red rings indicate ratio >3x — a strong profile mismatch signal." /></h2>

            {/* Occupation color legend */}
            <div className="flex flex-wrap gap-x-3 gap-y-1 mb-2">
              {occupations.slice(0, 8).map((occ) => (
                <span key={occ} className="flex items-center gap-1 text-xs text-slate-400">
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: getOccColor(occ, occupations) }}
                  />
                  {occ}
                </span>
              ))}
              {occupations.length > 8 && (
                <span className="text-xs text-slate-500">+{occupations.length - 8} more</span>
              )}
            </div>

            <p className="text-xs text-slate-500 mb-3">
              <span
                className="inline-block w-3 h-3 rounded-full border-2 border-red-500 mr-1 align-middle"
                style={{ backgroundColor: "transparent" }}
              />
              Red ring = ratio &gt; 3x (outlier)
            </p>

            <div className="h-[400px]">
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 20, right: 30, bottom: 30, left: 30 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis
                    type="number"
                    dataKey="declared_income"
                    name="Declared Income"
                    scale="log"
                    domain={["auto", "auto"]}
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                    label={{
                      value: "Declared Income (₹)",
                      position: "insideBottom",
                      offset: -10,
                      fill: "#64748b",
                      fontSize: 12,
                    }}
                  />
                  <YAxis
                    type="number"
                    dataKey="actual_volume"
                    name="Actual Volume"
                    scale="log"
                    domain={["auto", "auto"]}
                    tick={{ fill: "#94a3b8", fontSize: 11 }}
                    label={{
                      value: "Actual Volume (₹)",
                      angle: -90,
                      position: "insideLeft",
                      fill: "#64748b",
                      fontSize: 12,
                    }}
                  />
                  <ZAxis type="number" dataKey="ratio" range={[30, 160]} />
                  <Tooltip
                    content={({ payload }) => {
                      if (!payload || !payload.length) return null;
                      const d = payload[0].payload;
                      const ratioColor =
                        d.ratio > 10 ? "#ef4444"
                        : d.ratio > 5 ? "#f97316"
                        : d.ratio > 3 ? "#eab308"
                        : "#22c55e";
                      return (
                        <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 text-xs shadow-xl">
                          <p className="text-white font-medium mb-1">{d.account_id}</p>
                          <p className="text-slate-300">Occupation: {d.occupation}</p>
                          <p className="text-slate-300">Income Bracket: {d.income_bracket}</p>
                          <p className="text-slate-300">
                            Declared Income: {formatINR(d.declared_income)}
                          </p>
                          <p className="text-slate-300">
                            Actual Volume: {formatINR(d.actual_volume)}
                          </p>
                          <p className="font-semibold mt-1" style={{ color: ratioColor }}>
                            Ratio: {d.ratio.toFixed(2)}x{d.ratio > 3 ? " ⚠ Outlier" : ""}
                          </p>
                        </div>
                      );
                    }}
                  />
                  <ReferenceLine
                    segment={[
                      { x: 10000, y: 10000 },
                      { x: 100000000, y: 100000000 },
                    ]}
                    stroke="#475569"
                    strokeDasharray="5 5"
                    label={{ value: "1:1 line", fill: "#64748b", fontSize: 10 }}
                  />
                  {/* Single Scatter with custom shape — red ring for ratio > 3x, colored by occupation */}
                  <Scatter
                    data={coloredScatterData}
                    shape={((props: Record<string, unknown>) => {
                      const cx = props.cx as number;
                      const cy = props.cy as number;
                      const payload = props.payload as { ratio: number; color: string } | undefined;
                      if (!payload || cx == null || cy == null) return <g />;
                      return (
                        <g>
                          {payload.ratio > 3 && (
                            <circle
                              cx={cx}
                              cy={cy}
                              r={10}
                              fill="none"
                              stroke="#ef4444"
                              strokeWidth={2}
                              opacity={0.85}
                            />
                          )}
                          <circle
                            cx={cx}
                            cy={cy}
                            r={5}
                            fill={payload.color || "#3b82f6"}
                            fillOpacity={0.85}
                          />
                        </g>
                      );
                    }) as unknown as (props: unknown) => JSX.Element}
                  />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

        {/* Right panel — Mismatch Table */}
        <div className="xl:col-span-2">
          <Card>
            <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
              <h2 className="text-lg font-semibold text-white">Top Mismatches<InfoTooltip text="Accounts ranked by mismatch ratio (actual volume ÷ declared income). A ratio of 10x means the account transacted 10x more than their declared income for the year. Ratios above 3x are highlighted as outliers requiring investigation." /></h2>
              <span className="text-xs text-slate-500">sorted by ratio ↓</span>
            </div>

            <FilterBar
              filters={PROFILE_FILTERS}
              values={filterValues}
              onChange={handleFilterChange}
              onReset={handleFilterReset}
            />

            {sortedMismatches.length === 0 ? (
              <EmptyState message="No mismatches detected" />
            ) : (
              (() => {
                const filtered = sortedMismatches.filter((m: Record<string, unknown>) => {
                  const ratio = (m.ratio as number) || 0;
                  const sev = getSeverity(ratio).label;
                  if (filterValues.severity && sev !== filterValues.severity) return false;
                  if (
                    filterValues.accountSearch &&
                    !String(m.account_id || "")
                      .toLowerCase()
                      .includes(filterValues.accountSearch.toLowerCase())
                  )
                    return false;
                  if (
                    filterValues.occupation &&
                    !String(m.occupation || "")
                      .toLowerCase()
                      .includes(filterValues.occupation.toLowerCase())
                  )
                    return false;
                  if (filterValues.minRatio && ratio < Number(filterValues.minRatio)) return false;
                  return true;
                });
                const totalPages = Math.ceil(filtered.length / MISMATCH_PER_PAGE);
                const paged = filtered.slice(
                  mismatchPage * MISMATCH_PER_PAGE,
                  (mismatchPage + 1) * MISMATCH_PER_PAGE
                );
                return (
                  <>
                    <div className="overflow-x-auto mt-3">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-slate-700 text-slate-400 uppercase tracking-wider">
                            <th className="text-left py-2 px-1.5">Account</th>
                            <th className="text-left py-2 px-1.5">Occupation</th>
                            <th className="text-right py-2 px-1.5">Declared</th>
                            <th className="text-right py-2 px-1.5">Actual</th>
                            <th className="text-right py-2 px-1.5">Ratio</th>
                            <th className="text-center py-2 px-1.5">Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {paged.map((m: Record<string, unknown>, i) => {
                            const ratio = (m.ratio as number) || 0;
                            const severity = getSeverity(ratio);
                            const id = m.account_id as string;
                            const isSelected = selectedId === id;
                            return (
                              <tr
                                key={i}
                                className={`border-b border-slate-800 transition-colors ${
                                  isSelected
                                    ? "bg-blue-900/20 border-blue-700/30"
                                    : "hover:bg-slate-800/50"
                                }`}
                              >
                                <td className="py-2 px-1.5 text-blue-400 font-mono">{id}</td>
                                <td className="py-2 px-1.5 text-slate-300 max-w-[90px] truncate">
                                  {m.occupation as string}
                                </td>
                                <td className="py-2 px-1.5 text-right text-slate-300">
                                  {formatINR(m.declared_income as number)}
                                </td>
                                <td className="py-2 px-1.5 text-right text-slate-300">
                                  {formatINR(m.actual_volume as number)}
                                </td>
                                <td
                                  className="py-2 px-1.5 text-right font-semibold"
                                  style={{
                                    color: RISK_COLORS[severity.label] || "#94a3b8",
                                  }}
                                >
                                  {ratio.toFixed(1)}x
                                </td>
                                <td className="py-2 px-1.5 text-center">
                                  <button
                                    onClick={() => handleViewDetails(id)}
                                    className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
                                      isSelected
                                        ? "bg-blue-600 text-white"
                                        : "bg-slate-700 text-slate-300 hover:bg-slate-600 hover:text-white"
                                    }`}
                                  >
                                    {isSelected ? "Close" : "View Details"}
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>

                    {totalPages > 1 && (
                      <div className="flex items-center justify-between mt-2 pt-2 border-t border-slate-800">
                        <span className="text-[10px] text-slate-500">
                          {filtered.length} items · Page {mismatchPage + 1}/{totalPages}
                        </span>
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => setMismatchPage(Math.max(0, mismatchPage - 1))}
                            disabled={mismatchPage === 0}
                            className="px-1.5 py-0.5 text-xs bg-slate-800 text-slate-400 rounded disabled:opacity-30 hover:text-white"
                          >
                            ←
                          </button>
                          <span className="text-[10px] text-slate-500 px-1">
                            {mismatchPage + 1}/{totalPages}
                          </span>
                          <button
                            onClick={() =>
                              setMismatchPage(Math.min(totalPages - 1, mismatchPage + 1))
                            }
                            disabled={mismatchPage >= totalPages - 1}
                            className="px-1.5 py-0.5 text-xs bg-slate-800 text-slate-400 rounded disabled:opacity-30 hover:text-white"
                          >
                            →
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                );
              })()
            )}
          </Card>
        </div>
      </div>

      {/* Account Detail Card — shown when a mismatch row is selected */}
      {selectedId && (
        <Card>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white">
              Account Detail —{" "}
              <span className="font-mono text-blue-400">{selectedId}</span>
            </h2>
            <div className="flex items-center gap-3">
              <Link
                href={`/graph?account=${selectedId}`}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                View in Graph →
              </Link>
              <button
                onClick={() => {
                  setSelectedId(null);
                  setAccountDetail(null);
                  setPeerGroupForSelected(null);
                }}
                className="text-slate-500 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>
          </div>

          {detailLoading && <Loader />}

          {accountDetail && !detailLoading && (() => {
            const acc = accountDetail.account;
            const declaredIncome = (acc.declared_annual_income as number) || 0;
            const totalInFlow = (acc.total_in_flow as number) || 0;
            const totalOutFlow = (acc.total_out_flow as number) || 0;
            const txnCount = (acc.txn_count as number) || 0;
            const incomeRatio = declaredIncome > 0 ? totalInFlow / declaredIncome : 0;

            // Top 3 features with highest values → suspicious characteristics
            const topFeatures = Object.entries(accountDetail.features || {})
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3);

            const riskColor = RISK_COLORS[accountDetail.risk_level] || "#94a3b8";

            return (
              <div className="space-y-4">
                {/* Row 1 — Risk score, role, scores */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                  {/* Risk score bar + badge */}
                  <div className="bg-slate-800/50 rounded-lg p-3 col-span-2">
                    <p className="text-xs text-slate-400 mb-2">Risk Score</p>
                    <div className="flex items-center gap-3">
                      <div className="flex-1 bg-slate-700 rounded-full h-3 overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{
                            width: `${Math.min(accountDetail.risk_score, 100)}%`,
                            backgroundColor: riskColor,
                          }}
                        />
                      </div>
                      <span className="text-sm font-bold" style={{ color: riskColor }}>
                        {accountDetail.risk_score.toFixed(1)}
                      </span>
                    </div>
                    <div className="mt-2">
                      <Badge
                        variant={
                          accountDetail.risk_level === "CRITICAL"
                            ? "danger"
                            : accountDetail.risk_level === "HIGH"
                            ? "warning"
                            : accountDetail.risk_level === "MEDIUM"
                            ? "info"
                            : "success"
                        }
                      >
                        {accountDetail.risk_level}
                      </Badge>
                    </div>
                  </div>

                  {/* Role */}
                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-1">Role</p>
                    <p className="text-sm text-white font-medium">{accountDetail.role}</p>
                    <p className="text-xs text-slate-500">
                      {(accountDetail.role_confidence * 100).toFixed(1)}% confidence
                    </p>
                  </div>

                  {/* Anomaly score */}
                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-1">Anomaly Score</p>
                    <p
                      className={`text-sm font-bold ${
                        accountDetail.anomaly_score >= 70
                          ? "text-red-400"
                          : accountDetail.anomaly_score >= 40
                          ? "text-orange-400"
                          : "text-green-400"
                      }`}
                    >
                      {accountDetail.anomaly_score.toFixed(1)}
                    </p>
                  </div>

                  {/* Fraud probability */}
                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-1">Fraud Probability</p>
                    <p
                      className={`text-sm font-bold ${
                        accountDetail.fraud_probability > 0.7
                          ? "text-red-400"
                          : accountDetail.fraud_probability > 0.4
                          ? "text-orange-400"
                          : "text-green-400"
                      }`}
                    >
                      {(accountDetail.fraud_probability * 100).toFixed(1)}%
                    </p>
                  </div>

                  {/* Priority */}
                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-1">Priority</p>
                    <p className="text-sm font-bold text-white">{accountDetail.priority}</p>
                  </div>
                </div>

                {/* Row 2 — Financial data */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-1">Total Inflow</p>
                    <p className="text-sm text-green-400 font-medium">{formatINR(totalInFlow)}</p>
                  </div>
                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-1">Total Outflow</p>
                    <p className="text-sm text-red-400 font-medium">{formatINR(totalOutFlow)}</p>
                  </div>
                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-1">Transaction Count</p>
                    <p className="text-sm text-white font-medium">{txnCount}</p>
                  </div>
                  {/* Declared income vs inflow ratio — red-highlighted if > 3x */}
                  <div
                    className={`rounded-lg p-3 ${
                      incomeRatio > 3
                        ? "bg-red-500/10 border border-red-500/30"
                        : "bg-slate-800/50"
                    }`}
                  >
                    <p className="text-xs text-slate-400 mb-1">Inflow / Declared Income</p>
                    <div className="flex items-center gap-1.5">
                      <p
                        className={`text-sm font-bold ${
                          incomeRatio > 3 ? "text-red-400" : "text-green-400"
                        }`}
                      >
                        {incomeRatio.toFixed(2)}x
                      </p>
                      {incomeRatio > 3 && (
                        <span className="text-[10px] text-red-400 font-medium">⚠ High</span>
                      )}
                    </div>
                    <p className="text-[10px] text-slate-500 mt-0.5">
                      Declared: {formatINR(declaredIncome)}/yr
                    </p>
                  </div>
                </div>

                {/* Row 3 — Suspicious characteristics + Peer group */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-2 font-medium uppercase tracking-wider">
                      Suspicious Characteristics
                    </p>
                    {topFeatures.length > 0 ? (
                      <div className="space-y-2">
                        {topFeatures.map(([key, val]) => (
                          <div key={key} className="flex items-center gap-2">
                            <span className="text-amber-400 text-xs">•</span>
                            <span className="text-xs text-slate-300 flex-1">
                              {key.replace(/_/g, " ")}
                            </span>
                            <span className="text-xs text-amber-400 font-medium">
                              {typeof val === "number" ? val.toFixed(3) : String(val)}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">No feature data available</p>
                    )}
                  </div>

                  <div className="bg-slate-800/50 rounded-lg p-3">
                    <p className="text-xs text-slate-400 mb-2 font-medium uppercase tracking-wider">
                      Peer Group
                    </p>
                    {peerGroupForSelected ? (
                      <div className="space-y-1.5">
                        <div className="flex justify-between">
                          <span className="text-xs text-slate-400">Avg Peer Volume</span>
                          <span className="text-xs text-green-400 font-medium">
                            {formatINR(peerGroupForSelected.peer_mean)}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-xs text-slate-400">Deviation from Peer</span>
                          <span
                            className={`text-xs font-bold ${
                              peerGroupForSelected.z_score > 3
                                ? "text-red-400"
                                : peerGroupForSelected.z_score > 2
                                ? "text-orange-400"
                                : "text-green-400"
                            }`}
                          >
                            {peerGroupForSelected.z_score.toFixed(2)}σ
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-xs text-slate-400">Peer Count</span>
                          <span className="text-xs text-slate-300">
                            {peerGroupForSelected.peer_count}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-xs text-slate-400">Peer Segment</span>
                          <span className="text-xs text-slate-300 truncate max-w-[140px]">
                            {peerGroupForSelected.occupation} · {peerGroupForSelected.income_bracket}
                          </span>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs text-slate-500">No peer group data available</p>
                    )}
                  </div>
                </div>

                <div className="mt-4 pt-4 border-t border-slate-700/50">
                  <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">AI Investigation Brief</h4>
                  <AIExplanationPanel accountId={selectedId} />
                </div>
              </div>
            );
          })()}
        </Card>
      )}

      {/* Peer Group Analysis — manual lookup */}
      <Card>
        <h2 className="text-lg font-semibold text-white mb-4">Peer Group Analysis</h2>
        <div className="flex gap-3 mb-6">
          <input
            type="text"
            value={peerAccountId}
            onChange={(e) => setPeerAccountId(e.target.value)}
            placeholder="Enter Account ID..."
            className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
            onKeyDown={(e) => e.key === "Enter" && handlePeerAnalysis()}
          />
          <button
            onClick={handlePeerAnalysis}
            disabled={peerLoading}
            className="px-5 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {peerLoading ? "Analyzing..." : "Analyze"}
          </button>
        </div>

        {peerLoading && <Loader />}

        {peerData && !peerLoading && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-slate-800/50 rounded-lg p-3">
                <p className="text-xs text-slate-400">Occupation</p>
                <p className="text-sm text-white font-medium">{peerData.occupation}</p>
              </div>
              <div className="bg-slate-800/50 rounded-lg p-3">
                <p className="text-xs text-slate-400">Income Bracket</p>
                <p className="text-sm text-white font-medium">{peerData.income_bracket}</p>
              </div>
              <div className="bg-slate-800/50 rounded-lg p-3">
                <p className="text-xs text-slate-400">Declared Income</p>
                <p className="text-sm text-white font-medium">{formatINR(peerData.declared_income)}</p>
              </div>
              <div className="bg-slate-800/50 rounded-lg p-3">
                <p className="text-xs text-slate-400">Actual Volume</p>
                <p className="text-sm text-white font-medium">{formatINR(peerData.actual_volume)}</p>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div className="bg-slate-800/50 rounded-lg p-3">
                <p className="text-xs text-slate-400">Peer Mean Volume</p>
                <p className="text-sm text-green-400 font-medium">{formatINR(peerData.peer_mean)}</p>
              </div>
              <div className="bg-slate-800/50 rounded-lg p-3">
                <p className="text-xs text-slate-400">Peer Std Dev</p>
                <p className="text-sm text-slate-300 font-medium">{formatINR(peerData.peer_std)}</p>
              </div>
              <div className="bg-slate-800/50 rounded-lg p-3">
                <p className="text-xs text-slate-400">Z-Score</p>
                <p
                  className={`text-sm font-bold ${
                    peerData.z_score > 3
                      ? "text-red-400"
                      : peerData.z_score > 2
                      ? "text-orange-400"
                      : "text-green-400"
                  }`}
                >
                  {peerData.z_score.toFixed(2)}
                </p>
              </div>
            </div>

            {/* Visual comparison bar */}
            <div className="bg-slate-800/50 rounded-lg p-4">
              <p className="text-xs text-slate-400 mb-3">Volume Comparison (Account vs Peer Mean)</p>
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-400 w-24">Account</span>
                  <div className="flex-1 bg-slate-700 rounded-full h-5 overflow-hidden">
                    <div
                      className="h-full bg-blue-500 rounded-full flex items-center justify-end pr-2"
                      style={{
                        width: `${Math.min(
                          (peerData.actual_volume /
                            Math.max(peerData.actual_volume, peerData.peer_mean)) *
                            100,
                          100
                        )}%`,
                      }}
                    >
                      <span className="text-[10px] text-white font-medium">
                        {formatINR(peerData.actual_volume)}
                      </span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-400 w-24">Peer Mean</span>
                  <div className="flex-1 bg-slate-700 rounded-full h-5 overflow-hidden">
                    <div
                      className="h-full bg-green-500 rounded-full flex items-center justify-end pr-2"
                      style={{
                        width: `${Math.min(
                          (peerData.peer_mean /
                            Math.max(peerData.actual_volume, peerData.peer_mean)) *
                            100,
                          100
                        )}%`,
                      }}
                    >
                      <span className="text-[10px] text-white font-medium">
                        {formatINR(peerData.peer_mean)}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
