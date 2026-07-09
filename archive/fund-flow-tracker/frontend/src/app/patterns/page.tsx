"use client";

import { useEffect, useState, useMemo } from "react";
import { api, PatternData } from "@/lib/api";
import { Card, StatCard, Loader, Badge, EmptyState, FilterBar, FilterOption, InfoTooltip } from "@/components/ui";
import { formatINR } from "@/lib/utils";
import GraphValidationDialog from "@/components/GraphValidationDialog";

type Tab = "layering" | "round_tripping" | "structuring" | "dormant" | "fan_in" | "fan_out" | "profile_mismatch" | "combined";

function GraphValidationButton({ accountId, onValidate }: { accountId: string; onValidate: (accountId: string) => void }) {
  if (!accountId) return null;
  return (
    <button
      onClick={() => onValidate(accountId)}
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-blue-600/20 border border-blue-500/30 text-[10px] text-blue-300 hover:bg-blue-600/30 transition-colors"
    >
      🕸️ Graph Validation
    </button>
  );
}

function severityVariant(severity: string): "danger" | "warning" | "success" | "info" {
  switch (severity?.toUpperCase()) {
    case "CRITICAL": case "HIGH": return "danger";
    case "MEDIUM": return "warning";
    case "LOW": return "success";
    default: return "info";
  }
}

const PATTERN_FILTERS: FilterOption[] = [
  {
    key: "severity",
    label: "Severity",
    type: "select",
    options: [
      { value: "CRITICAL", label: "Critical" },
      { value: "HIGH", label: "High" },
      { value: "MEDIUM", label: "Medium" },
      { value: "LOW", label: "Low" },
    ],
  },
  { key: "minAmount", label: "Min Amount", type: "number", placeholder: "Min ₹" },
  { key: "maxAmount", label: "Max Amount", type: "number", placeholder: "Max ₹" },
  { key: "accountSearch", label: "Account ID", type: "text", placeholder: "Search account..." },
];

function filterPatternItems(items: unknown[], filters: Record<string, string>): unknown[] {
  return items.filter((item) => {
    const d = item as Record<string, unknown>;
    if (filters.severity && String(d.severity || "").toUpperCase() !== filters.severity.toUpperCase()) return false;
    if (filters.minAmount && Number(d.total_amount || 0) < Number(filters.minAmount)) return false;
    if (filters.maxAmount && Number(d.total_amount || 0) > Number(filters.maxAmount)) return false;
    if (filters.accountSearch) {
      const accounts = (d.accounts || d.account || d.account_id || "") as string | string[];
      const searchLower = filters.accountSearch.toLowerCase();
      if (Array.isArray(accounts)) {
        if (!accounts.some(a => String(a).toLowerCase().includes(searchLower))) return false;
      } else {
        if (!String(accounts).toLowerCase().includes(searchLower)) return false;
      }
    }
    return true;
  });
}

export default function PatternsPage() {
  const [data, setData] = useState<PatternData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<Tab>("layering");
  const [searchAccount, setSearchAccount] = useState("");
  const [suspiciousResult, setSuspiciousResult] = useState<Record<string, unknown> | null>(null);
  const [detecting, setDetecting] = useState(false);
  const [filterValues, setFilterValues] = useState<Record<string, string>>({});
  const [validationOpen, setValidationOpen] = useState(false);
  const [validationAccountId, setValidationAccountId] = useState<string | null>(null);

  const openValidation = (accountId: string) => {
    setValidationAccountId(accountId);
    setValidationOpen(true);
  };

  useEffect(() => {
    api.getPatterns().then(setData).finally(() => setLoading(false));
  }, []);

  const handleFilterChange = (key: string, value: string) => {
    setFilterValues((prev) => ({ ...prev, [key]: value }));
  };
  const handleFilterReset = () => setFilterValues({});

  if (loading) return <Loader />;
  if (!data) return <EmptyState message="Failed to load pattern data" />;

  const p = (data.patterns as Record<string, unknown>) || {};
  const layering = (p.layering as unknown[]) || [];
  const roundTripping = (p.round_tripping as unknown[]) || (p.round_trip as unknown[]) || [];
  const structuring = (p.structuring as Record<string, unknown>) || {};
  const classic = Array.isArray(structuring) ? structuring : (structuring.classic as unknown[]) || [];
  const split = Array.isArray(structuring) ? [] : (structuring.split as unknown[]) || [];
  const dormant = (p.dormant_activation as unknown[]) || (p.dormancy as unknown[]) || [];
  const fanIn = (p.fan_in as unknown[]) || [];
  const fanOut = (p.fan_out as unknown[]) || [];
  const profileMismatch = (p.profile_mismatch as unknown[]) || [];
  const combined = (p.combined as unknown[]) || [];

  const tabs: { key: Tab; label: string; icon: string; color: "blue" | "purple" | "orange" | "red" | "green" | "yellow"; tooltip: string }[] = [
    { key: "layering", label: "Layering", icon: "🔗", color: "blue", tooltip: "Layering is Stage 2 of money laundering. After placing illicit funds in the banking system, launderers move money through multiple accounts to obscure its origin. We detect accounts appearing in chains of 3+ rapid transfers." },
    { key: "round_tripping", label: "Round-Tripping", icon: "🔄", color: "purple", tooltip: "Round-trip transactions return funds to the originating account — directly or through intermediaries. This creates fictitious trading activity or hides the true ownership of funds. Even a 4–5 hop return loop counts." },
    { key: "structuring", label: "Structuring", icon: "💰", color: "orange", tooltip: "Structuring (Smurfing) means deliberately splitting large sums into smaller amounts to stay below the ₹10 lakh Cash Transaction Report threshold. We flag accounts where transaction amounts statistically cluster in the ₹9–9.9L band." },
    { key: "dormant", label: "Dormant", icon: "💤", color: "red", tooltip: "A dormant account that suddenly becomes active with high-value transactions is a red flag. Criminals acquire or reactivate old accounts specifically to avoid new-account monitoring rules. We flag accounts inactive for 90+ days before sudden high activity." },
    { key: "fan_in", label: "Fan-In", icon: "📥", color: "green", tooltip: "Fan-In accounts aggregate funds from many sources before a large outflow. Combined with rapid forwarding, this indicates a collector node in a money laundering network." },
    { key: "fan_out", label: "Fan-Out", icon: "📤", color: "yellow", tooltip: "Fan-Out accounts distribute funds to an unusually large number of recipients in a short time. This pattern is typical of mule coordinator accounts that spread laundered money across a network to make recovery difficult." },
    { key: "profile_mismatch", label: "Profile", icon: "👤", color: "orange", tooltip: "Profile mismatch compares an account holder's declared occupation and income bracket against their actual transaction volume. A construction daily-wage worker transacting ₹2 crore per month is a textbook mismatch." },
    { key: "combined", label: "Combined", icon: "⚡", color: "red", tooltip: "Accounts flagged by multiple pattern detectors simultaneously. Co-occurrence of two or more AML typologies in the same account significantly raises the probability of genuine criminal activity." },
  ];

  const counts: Record<Tab, number> = {
    layering: layering.length,
    round_tripping: roundTripping.length,
    structuring: classic.length + split.length,
    dormant: dormant.length,
    fan_in: fanIn.length,
    fan_out: fanOut.length,
    profile_mismatch: profileMismatch.length,
    combined: combined.length,
  };

  async function handleDetect() {
    if (!searchAccount.trim()) return;
    setDetecting(true);
    setSuspiciousResult(null);
    try {
      const res = await api.getFirstSuspicious(searchAccount.trim());
      setSuspiciousResult(res.found ? (res.data || { found: true }) : { found: false });
    } catch {
      setSuspiciousResult({ error: "Failed to detect" });
    } finally {
      setDetecting(false);
    }
  }

  return (
    <div className="space-y-6 p-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Pattern Detector <InfoTooltip text="Pattern Detector runs six rule-based AML detectors on every account. Unlike ML models, rule-based detectors produce explainable, auditable results — each flag maps directly to a named typology in FATF guidance and RBI AML circulars." /></h1>
        <p className="text-xs text-slate-400 mt-1">Automated detection of 6 AML pattern types</p>
      </div>

      {/* Overview Stats */}
      <p className="text-[10px] text-slate-500 -mb-1 flex items-center gap-1">
        <InfoTooltip text="Number of unique accounts exhibiting this pattern in the currently loaded dataset. Click to see the flagged accounts and their transaction chains." />
        Counts show unique flagged accounts per pattern
      </p>
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        {tabs.map((t) => (
          <StatCard key={t.key} label={<>{t.label} <InfoTooltip text={t.tooltip} /></>} value={counts[t.key]} icon={t.icon} color={t.color} />
        ))}
        <StatCard label="Flagged" value={data.flagged_accounts?.length || 0} icon="🚨" color="red" />
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap gap-1 border-b border-slate-700 pb-2">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            className={`px-4 py-2 text-sm rounded-t-lg transition-colors ${
              activeTab === t.key
                ? "bg-slate-700 text-white font-medium"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
            }`}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {/* Filters */}
      <FilterBar filters={PATTERN_FILTERS} values={filterValues} onChange={handleFilterChange} onReset={handleFilterReset} />

      {/* Tab Content */}
      <div className="min-h-[300px]">
        {activeTab === "layering" && <LayeringTab data={filterPatternItems(layering, filterValues)} onValidate={openValidation} />}
        {activeTab === "round_tripping" && <RoundTrippingTab data={filterPatternItems(roundTripping, filterValues)} onValidate={openValidation} />}
        {activeTab === "structuring" && <StructuringTab classic={filterPatternItems(classic, filterValues)} split={filterPatternItems(split, filterValues)} />}
        {activeTab === "dormant" && <DormantTab data={filterPatternItems(dormant, filterValues)} />}
        {activeTab === "fan_in" && <FanInTab data={filterPatternItems(fanIn, filterValues)} onValidate={openValidation} />}
        {activeTab === "fan_out" && <FanOutTab data={filterPatternItems(fanOut, filterValues)} onValidate={openValidation} />}
        {activeTab === "profile_mismatch" && <ProfileMismatchTab data={filterPatternItems(profileMismatch, filterValues)} />}
        {activeTab === "combined" && <CombinedTab data={filterPatternItems(combined, filterValues)} />}
      </div>

      {/* First Suspicious Point Detector */}
      <Card>
        <h2 className="text-lg font-semibold text-white mb-4">🎯 First Suspicious Point Detector</h2>
        <div className="flex gap-3 items-center">
          <input
            type="text"
            value={searchAccount}
            onChange={(e) => setSearchAccount(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleDetect()}
            placeholder="Enter Account ID (e.g., ACC_001)"
            className="flex-1 px-4 py-2 rounded-lg bg-slate-800 border border-slate-600 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={handleDetect}
            disabled={detecting}
            className="px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-600 text-white rounded-lg font-medium transition-colors"
          >
            {detecting ? "Detecting..." : "Detect"}
          </button>
        </div>
        {suspiciousResult && (
          <div className="mt-4 p-4 rounded-lg bg-slate-800 border border-slate-700">
            {suspiciousResult.error ? (
              <p className="text-red-400">{String(suspiciousResult.error)}</p>
            ) : suspiciousResult.found === false ? (
              <p className="text-slate-400">No suspicious activity detected for this account.</p>
            ) : (
              <div className="space-y-2">
                <p className="text-green-400 font-medium">⚠️ Suspicious Point Found</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-2">
                  {suspiciousResult.txn_id != null && (
                    <div><p className="text-xs text-slate-500">Transaction ID</p><p className="text-white text-sm font-mono">{String(suspiciousResult.txn_id)}</p></div>
                  )}
                  {suspiciousResult.timestamp != null && (
                    <div><p className="text-xs text-slate-500">Timestamp</p><p className="text-white text-sm">{String(suspiciousResult.timestamp)}</p></div>
                  )}
                  {suspiciousResult.amount != null && (
                    <div><p className="text-xs text-slate-500">Amount</p><p className="text-white text-sm">{formatINR(Number(suspiciousResult.amount))}</p></div>
                  )}
                  {suspiciousResult.z_score != null && (
                    <div><p className="text-xs text-slate-500">Z-Score</p><p className="text-orange-400 text-sm font-bold">{Number(suspiciousResult.z_score).toFixed(2)}</p></div>
                  )}
                  {suspiciousResult.detection_method != null && (
                    <div><p className="text-xs text-slate-500">Detection Method</p><p className="text-blue-400 text-sm">{String(suspiciousResult.detection_method)}</p></div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </Card>

      <GraphValidationDialog
        accountId={validationAccountId}
        open={validationOpen}
        onClose={() => setValidationOpen(false)}
      />
    </div>
  );
}

/* ─── Tab Components ──────────────────────────────────────────────────────── */

function LayeringTab({ data, onValidate }: { data: unknown[]; onValidate: (accountId: string) => void }) {
  if (!data.length) return <EmptyState message="No layering patterns detected" />;
  return (
    <div className="grid gap-4">
      {data.map((item: unknown, i: number) => {
        const d = item as Record<string, unknown>;
        // accounts is a string[], chain is an array of transaction objects
        const accounts = (d.accounts || d.account_ids || []) as string[];
        const chain = (d.chain || []) as Record<string, unknown>[];
        return (
          <Card key={i}>
            <div className="flex items-start justify-between">
              <div className="space-y-2 flex-1">
                <div className="flex items-center gap-3">
                  <span className="text-lg">🔗</span>
                  <span className="text-white font-medium">Layering Chain #{i + 1}</span>
                  <Badge variant={severityVariant(String(d.severity))}>{String(d.severity)}</Badge>
                  {accounts[0] && <GraphValidationButton accountId={accounts[0]} onValidate={onValidate} />}
                </div>
                <div className="flex flex-wrap items-center gap-1 mt-2 font-mono text-sm">
                  {accounts.map((acc: string, j: number) => (
                    <span key={j} className="flex items-center">
                      <span className="px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded">{typeof acc === 'string' ? acc : JSON.stringify(acc)}</span>
                      {j < accounts.length - 1 && <span className="text-slate-500 mx-1">→</span>}
                    </span>
                  ))}
                </div>
                {/* Transaction details */}
                {chain.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {chain.map((txn, j: number) => {
                      // Defensive: ensure all fields are stringified, and log if any are objects
                      const from = typeof txn.from === 'string' || typeof txn.from === 'number' ? String(txn.from).replace("ACC_", "") : JSON.stringify(txn.from);
                      const to = typeof txn.to === 'string' || typeof txn.to === 'number' ? String(txn.to).replace("ACC_", "") : JSON.stringify(txn.to);
                      const amount = typeof txn.amount === 'string' || typeof txn.amount === 'number' ? formatINR(Number(txn.amount)) : JSON.stringify(txn.amount);
                      const channel = typeof txn.channel === 'string' || typeof txn.channel === 'number' ? String(txn.channel) : JSON.stringify(txn.channel);
                      // Optionally, log to console if any field is an object (for debugging)
                      if (typeof txn.from === 'object' || typeof txn.to === 'object' || typeof txn.amount === 'object' || typeof txn.channel === 'object') {
                        // eslint-disable-next-line no-console
                        console.warn('LayeringTab: txn field is object', { txn });
                      }
                      return (
                        <div key={j} className="flex items-center gap-2 text-xs text-slate-400">
                          <span className="text-blue-300 font-mono">{from}</span>
                          <span className="text-slate-600">→</span>
                          <span className="text-blue-300 font-mono">{to}</span>
                          <span className="text-green-400">{amount}</span>
                          <span className="text-slate-600">{channel}</span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-3 border-t border-slate-700">
              <div><p className="text-xs text-slate-500">Hops</p><p className="text-white font-bold">{String(d.hops || 0)}</p></div>
              <div><p className="text-xs text-slate-500">Time Span</p><p className="text-white font-bold">{(Number(d.time_span_minutes) || 0).toFixed(0)} min</p></div>
              <div><p className="text-xs text-slate-500">Total Amount</p><p className="text-white font-bold">{formatINR(Number(d.total_amount))}</p></div>
              <div>
                <p className="text-xs text-slate-500">Amount Decay</p>
                <p className="text-orange-400 font-bold">
                  {(() => {
                    const decay = Number(d.amount_decay) || 0;
                    const mode = String(d.detection_mode || d.pattern_type || "");
                    if (decay < 0.01) {
                      return (mode === "extended" || mode === "stack")
                        ? "Extended pattern"
                        : "< 1%";
                    }
                    return `${(decay * 100).toFixed(1)}%`;
                  })()}
                </p>
              </div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function RoundTrippingTab({ data, onValidate }: { data: unknown[]; onValidate: (accountId: string) => void }) {
  if (!data.length) return <EmptyState message="No round-tripping patterns detected" />;
  return (
    <div className="grid gap-4">
      {data.map((item: unknown, i: number) => {
        const d = item as Record<string, unknown>;
        const nodes = (d.cycle_nodes || []) as string[];
        return (
          <Card key={i}>
            <div className="flex items-center gap-3 mb-3">
              <span className="text-lg">🔄</span>
              <span className="text-white font-medium">Cycle #{i + 1}</span>
              <Badge variant={severityVariant(String(d.severity))}>{String(d.severity)}</Badge>
              {nodes[0] && <GraphValidationButton accountId={nodes[0]} onValidate={onValidate} />}
            </div>
            <div className="flex flex-wrap items-center gap-1 font-mono text-sm mb-4">
              {nodes.map((acc: string, j: number) => (
                <span key={j} className="flex items-center">
                  <span className="px-2 py-0.5 bg-purple-500/20 text-purple-300 rounded">{acc}</span>
                  <span className="text-slate-500 mx-1">→</span>
                </span>
              ))}
              {nodes.length > 0 && <span className="px-2 py-0.5 bg-purple-500/20 text-purple-300 rounded">{nodes[0]}</span>}
            </div>
            <div className="grid grid-cols-3 gap-4 pt-3 border-t border-slate-700">
              <div><p className="text-xs text-slate-500">Cycle Length</p><p className="text-white font-bold">{String(d.cycle_length || 0)}</p></div>
              <div><p className="text-xs text-slate-500">Total Amount</p><p className="text-white font-bold">{formatINR(Number(d.total_amount))}</p></div>
              <div><p className="text-xs text-slate-500">Time Span</p><p className="text-white font-bold">{(Number(d.time_span_hours) || 0).toFixed(1)} hrs</p></div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function StructuringTab({ classic, split }: { classic: unknown[]; split: unknown[] }) {
  return (
    <div className="space-y-6">
      {/* Classic Structuring */}
      <div>
        <h3 className="text-white font-semibold mb-3">💰 Classic Structuring</h3>
        {classic.length === 0 ? (
          <EmptyState message="No classic structuring detected" />
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700">
                  <th className="text-left py-2 px-3">Account ID</th>
                  <th className="text-left py-2 px-3">Transactions</th>
                  <th className="text-left py-2 px-3">Count</th>
                  <th className="text-left py-2 px-3">Severity</th>
                </tr>
              </thead>
              <tbody>
                {classic.map((item: unknown, i: number) => {
                  const d = item as Record<string, unknown>;
                  return (
                    <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/50">
                      <td className="py-2 px-3 text-white font-mono">{String(d.account_id)}</td>
                      <td className="py-2 px-3 text-slate-300">{String(d.transactions || d.count || "-")}</td>
                      <td className="py-2 px-3 text-slate-300">{String(d.count || "-")}</td>
                      <td className="py-2 px-3"><Badge variant={severityVariant(String(d.severity))}>{String(d.severity)}</Badge></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        )}
      </div>

      {/* Split Structuring */}
      <div>
        <h3 className="text-white font-semibold mb-3">✂️ Split Structuring</h3>
        {split.length === 0 ? (
          <EmptyState message="No split structuring detected" />
        ) : (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 border-b border-slate-700">
                  <th className="text-left py-2 px-3">Account ID</th>
                  <th className="text-left py-2 px-3">Date</th>
                  <th className="text-left py-2 px-3">Total Amount</th>
                  <th className="text-left py-2 px-3">Count</th>
                  <th className="text-left py-2 px-3">Severity</th>
                </tr>
              </thead>
              <tbody>
                {split.map((item: unknown, i: number) => {
                  const d = item as Record<string, unknown>;
                  return (
                    <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/50">
                      <td className="py-2 px-3 text-white font-mono">{String(d.account_id)}</td>
                      <td className="py-2 px-3 text-slate-300">{String(d.date || "-")}</td>
                      <td className="py-2 px-3 text-slate-300">{formatINR(Number(d.total_amount))}</td>
                      <td className="py-2 px-3 text-slate-300">{String(d.count || "-")}</td>
                      <td className="py-2 px-3"><Badge variant={severityVariant(String(d.severity))}>{String(d.severity)}</Badge></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}

function DormantTab({ data }: { data: unknown[] }) {
  if (!data.length) return <EmptyState message="No dormant activation patterns detected" />;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {data.map((item: unknown, i: number) => {
        const d = item as Record<string, unknown>;
        const dormancyDays = Number(d.dormancy_days);
        return (
          <Card key={i}>
            <div className="flex items-center gap-3 mb-3">
              <span className="text-lg">💤</span>
              <span className="text-white font-medium font-mono">{String(d.account_id)}</span>
              <Badge variant={severityVariant(String(d.severity))}>{String(d.severity)}</Badge>
            </div>
            {/* Dormancy visualization */}
            <div className="flex items-center gap-2 mb-4">
              <div className="flex-1 h-3 bg-slate-700 rounded-full overflow-hidden relative">
                <div
                  className="h-full bg-slate-500 rounded-full"
                  style={{ width: `${Math.min(dormancyDays / 365 * 100, 85)}%` }}
                />
                <div className="absolute right-1 top-0 h-full w-3 bg-red-500 rounded-full animate-pulse" />
              </div>
              <span className="text-xs text-slate-500 whitespace-nowrap">💥 Burst</span>
            </div>
            <div className="grid grid-cols-3 gap-4 pt-3 border-t border-slate-700">
              <div><p className="text-xs text-slate-500">Dormancy</p><p className="text-white font-bold">{dormancyDays} days</p></div>
              <div><p className="text-xs text-slate-500">Burst Txns</p><p className="text-white font-bold">{String(d.burst_txn_count)}</p></div>
              <div><p className="text-xs text-slate-500">Burst Amount</p><p className="text-white font-bold">{formatINR(Number(d.burst_total_amount))}</p></div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function FanInTab({ data, onValidate }: { data: unknown[]; onValidate: (accountId: string) => void }) {
  if (!data.length) return <EmptyState message="No fan-in patterns detected" />;
  return (
    <div className="grid gap-4">
      {data.map((item: unknown, i: number) => {
        const d = item as Record<string, unknown>;
        const sources = (d.sources || []) as string[];
        return (
          <Card key={i}>
            <div className="flex items-center gap-3 mb-3">
              <span className="text-lg">📥</span>
              <span className="text-white font-medium">Sink: <span className="font-mono text-green-400">{String(d.sink_account ?? d.hub_account)}</span></span>
              <Badge variant={severityVariant(String(d.severity))}>{String(d.severity)}</Badge>
              {(d.sink_account ?? d.hub_account) != null && <GraphValidationButton accountId={String(d.sink_account ?? d.hub_account)} onValidate={onValidate} />}
            </div>
            {sources.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {sources.map((s: string, j: number) => (
                  <span key={j} className="px-2 py-0.5 bg-green-500/15 text-green-300 rounded text-xs font-mono">{s}</span>
                ))}
              </div>
            )}
            <div className="grid grid-cols-3 gap-4 pt-3 border-t border-slate-700">
              <div><p className="text-xs text-slate-500">Unique Sources</p><p className="text-white font-bold">{String(d.unique_sources)}</p></div>
              <div><p className="text-xs text-slate-500">Total Amount</p><p className="text-white font-bold">{formatINR(Number(d.total_amount))}</p></div>
              <div><p className="text-xs text-slate-500">Severity</p><p className="text-white font-bold">{String(d.severity)}</p></div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function FanOutTab({ data, onValidate }: { data: unknown[]; onValidate: (accountId: string) => void }) {
  if (!data.length) return <EmptyState message="No fan-out patterns detected" />;
  return (
    <div className="grid gap-4">
      {data.map((item: unknown, i: number) => {
        const d = item as Record<string, unknown>;
        const destinations = (d.destinations || []) as string[];
        return (
          <Card key={i}>
            <div className="flex items-center gap-3 mb-3">
              <span className="text-lg">📤</span>
              <span className="text-white font-medium">Source: <span className="font-mono text-yellow-400">{String(d.source_account ?? d.hub_account)}</span></span>
              <Badge variant={severityVariant(String(d.severity))}>{String(d.severity)}</Badge>
              {(d.source_account ?? d.hub_account) != null && <GraphValidationButton accountId={String(d.source_account ?? d.hub_account)} onValidate={onValidate} />}
            </div>
            {destinations.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-3">
                {destinations.map((dest: string, j: number) => (
                  <span key={j} className="px-2 py-0.5 bg-yellow-500/15 text-yellow-300 rounded text-xs font-mono">{dest}</span>
                ))}
              </div>
            )}
            <div className="grid grid-cols-3 gap-4 pt-3 border-t border-slate-700">
              <div><p className="text-xs text-slate-500">Unique Destinations</p><p className="text-white font-bold">{String(d.unique_destinations)}</p></div>
              <div><p className="text-xs text-slate-500">Total Amount</p><p className="text-white font-bold">{formatINR(Number(d.total_amount))}</p></div>
              <div><p className="text-xs text-slate-500">Severity</p><p className="text-white font-bold">{String(d.severity)}</p></div>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function ProfileMismatchTab({ data }: { data: unknown[] }) {
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 25;
  const totalPages = Math.ceil(data.length / PAGE_SIZE);
  const paged = data.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  if (!data.length) return <EmptyState message="No profile mismatch patterns detected" />;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-slate-400">{data.length} accounts with volume/profile mismatches</p>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0} className="px-2 py-1 text-xs bg-slate-800 text-slate-300 rounded disabled:opacity-30">←</button>
            <span className="text-xs text-slate-500">{page + 1}/{totalPages}</span>
            <button onClick={() => setPage(Math.min(totalPages - 1, page + 1))} disabled={page >= totalPages - 1} className="px-2 py-1 text-xs bg-slate-800 text-slate-300 rounded disabled:opacity-30">→</button>
          </div>
        )}
      </div>
      <Card className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-slate-400 border-b border-slate-700">
              <th className="text-left py-2 px-3">Account</th>
              <th className="text-left py-2 px-3">Occupation</th>
              <th className="text-left py-2 px-3">Declared Income</th>
              <th className="text-left py-2 px-3">Actual Volume</th>
              <th className="text-left py-2 px-3">Ratio</th>
              <th className="text-left py-2 px-3">Type</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((item: unknown, i: number) => {
              const d = item as Record<string, unknown>;
              const ratio = Number(d.volume_to_income_ratio || 0);
              return (
                <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/50">
                  <td className="py-2 px-3 text-white font-mono text-xs">{String(d.account_id || (Array.isArray(d.account_ids) ? d.account_ids[0] : "") || "-")}</td>
                  <td className="py-2 px-3 text-slate-300 text-xs">{String(d.occupation || "-")}</td>
                  <td className="py-2 px-3 text-slate-300 text-xs">{formatINR(Number(d.declared_annual_income || 0))}</td>
                  <td className="py-2 px-3 text-slate-300 text-xs">{formatINR(Number(d.actual_volume || 0))}</td>
                  <td className="py-2 px-3">
                    <span className={`text-xs font-bold ${ratio > 5 ? "text-red-400" : ratio > 2 ? "text-orange-400" : "text-yellow-400"}`}>
                      {ratio.toFixed(1)}x
                    </span>
                  </td>
                  <td className="py-2 px-3 text-xs text-slate-400">{String(d.sub_type || "-")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function CombinedTab({ data }: { data: unknown[] }) {
  if (!data.length) return <EmptyState message="No combined patterns detected" />;
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-slate-400 border-b border-slate-700">
            <th className="text-left py-2 px-3">Account ID</th>
            <th className="text-left py-2 px-3">Patterns</th>
            <th className="text-left py-2 px-3">Count</th>
            <th className="text-left py-2 px-3">Combo Score</th>
            <th className="text-left py-2 px-3">Severity</th>
          </tr>
        </thead>
        <tbody>
          {data.map((item: unknown, i: number) => {
            const d = item as Record<string, unknown>;
            const patterns = (d.patterns || []) as string[];
            return (
              <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/50">
                <td className="py-2 px-3 text-white font-mono">{String(d.account_id)}</td>
                <td className="py-2 px-3">
                  <div className="flex flex-wrap gap-1">
                    {patterns.map((pat: string, j: number) => (
                      <Badge key={j} variant="info">{pat}</Badge>
                    ))}
                  </div>
                </td>
                <td className="py-2 px-3 text-slate-300">{String(d.pattern_count)}</td>
                <td className="py-2 px-3 text-orange-400 font-bold">{Number(d.combo_score).toFixed(2)}</td>
                <td className="py-2 px-3"><Badge variant={severityVariant(String(d.severity))}>{String(d.severity)}</Badge></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}
