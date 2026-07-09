"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { api, GraphData } from "@/lib/api";
import { Card, InfoTooltip } from "@/components/ui";
import GraphValidationDialog from "@/components/GraphValidationDialog";

const CytoscapeGraph = dynamic(() => import("@/components/CytoscapeGraph"), { ssr: false });

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
      setExplanation("Could not generate explanation.");
    } finally { setLoading(false); }
  };
  return (
    <div className="mt-1.5">
      <button onClick={generate}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-violet-600/20 border border-violet-500/30 text-[10px] text-violet-300 hover:bg-violet-600/30 transition-colors">
        🤖 {shown && explanation ? "Hide" : "Why flagged? (AI)"}
      </button>
      {shown && (
        <div className="mt-1.5 rounded-lg bg-violet-500/5 border border-violet-500/20 p-2.5 text-xs text-slate-300 leading-relaxed">
          {loading ? <span className="text-violet-400 animate-pulse">Generating explanation…</span> : explanation}
        </div>
      )}
    </div>
  );
}

interface IngestionResult {
  status: string;
  date?: string;
  total_transactions?: number;
  total_accounts?: number;
  new_accounts?: number;
  existing_accounts?: number;
  alerts_generated?: number;
  patterns_detected?: Record<string, number>;
  processing_time_sec?: number;
  system_refreshed?: boolean;
  refresh_warning?: string;
  reason?: string;
  file_hash?: string;
  row_preview?: (Record<string, unknown> & { occupation?: string; declared_annual_income?: number })[];
  hourly_activity?: { hour: string; count: number }[];
  top_accounts?: { account_id: string; txn_count: number; total_amount: number }[];
  graph_data?: GraphData;
  priority_accounts?: {
    account_id: string;
    risk_score: number;
    risk_level: string;
    priority: string;
    role: string;
    patterns: string[];
    total_inflow: number;
    total_outflow: number;
    anomaly_score: number;
  }[];
  channel_distribution?: { channel: string; count: number }[];
  profile_mismatches?: {
    account_id: string;
    occupation: string;
    declared_income: number;
    actual_volume: number;
    ratio: number;
    risk_score: number;
  }[];
  speed_alerts?: { account_id: string; txn_count: number; risk_level: string }[];
}

function truncate(s: string, n = 12) {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

const RISK_BADGE: Record<string, string> = {
  CRITICAL: "bg-red-500/20 text-red-400 border border-red-500/30",
  HIGH:     "bg-orange-500/20 text-orange-400 border border-orange-500/30",
  MEDIUM:   "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
  LOW:      "bg-green-500/20 text-green-400 border border-green-500/30",
};

const PRIORITY_BADGE: Record<string, string> = {
  P1: "bg-red-600/30 text-red-300 border border-red-500/40",
  P2: "bg-orange-600/30 text-orange-300 border border-orange-500/40",
  P3: "bg-yellow-600/30 text-yellow-300 border border-yellow-500/40",
  P4: "bg-slate-600/30 text-slate-400 border border-slate-500/40",
};

function fmt(n: number) {
  if (n >= 1_00_00_000) return `₹${(n / 1_00_00_000).toFixed(1)}Cr`;
  if (n >= 1_00_000) return `₹${(n / 1_00_000).toFixed(1)}L`;
  if (n >= 1_000) return `₹${(n / 1_000).toFixed(1)}K`;
  return `₹${n.toLocaleString()}`;
}

function ratioColor(r: number) {
  if (r > 10) return "text-red-400";
  if (r > 5) return "text-orange-400";
  return "text-yellow-400";
}

function Paginator({ page, total, perPage, onChange }: { page: number; total: number; perPage: number; onChange: (p: number) => void }) {
  const pages = Math.ceil(total / perPage);
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-between mt-3">
      <span className="text-xs text-slate-500">Page {page + 1} of {pages}</span>
      <div className="flex gap-2">
        <button disabled={page === 0} onClick={() => onChange(page - 1)}
          className="px-2.5 py-1 rounded text-xs bg-slate-800 text-slate-400 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700">
          ← Prev
        </button>
        <button disabled={page >= pages - 1} onClick={() => onChange(page + 1)}
          className="px-2.5 py-1 rounded text-xs bg-slate-800 text-slate-400 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed border border-slate-700">
          Next →
        </button>
      </div>
    </div>
  );
}

const STORAGE_KEY = "tracex_last_ingest_result";

function readStoredResult(): IngestionResult | null {
  if (typeof window === "undefined") return null;
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch {
    return null;
  }
}

export default function IngestPage() {
  const [file, setFile] = useState<File | null>(null);
  const [date, setDate] = useState("");
  const [force, setForce] = useState(false);
  const [loading, setLoading] = useState(false);
  // Restored synchronously from localStorage via lazy initializer (not an effect)
  // so there's no post-mount flash and no synchronous setState-in-effect.
  const [result, setResult] = useState<IngestionResult | null>(readStoredResult);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [history, setHistory] = useState<Record<string, unknown>[] | null>(null);
  const [loadingHistory, setLoadingHistory] = useState<string | null>(null);
  const [priorityPage, setPriorityPage] = useState(0);
  const [profilePage, setProfilePage] = useState(0);
  const [validationOpen, setValidationOpen] = useState(false);
  const [validationAccountId, setValidationAccountId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const openValidation = (accountId: string) => {
    setValidationAccountId(accountId);
    setValidationOpen(true);
  };

  // Reset pagination whenever result changes — adjust state during render
  // (React's documented pattern for "resetting state when a prop/value changes",
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes)
  // instead of in an effect, since it needs no synchronization with anything external.
  const [prevResult, setPrevResult] = useState(result);
  if (prevResult !== result) {
    setPrevResult(result);
    setPriorityPage(0);
    setProfilePage(0);
  }

  const loadHistory = useCallback(async () => {
    try {
      const h = await api.getIngestionHistory();
      setHistory(h);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  // On mount: clear the restored result if the system has no data loaded.
  useEffect(() => {
    api.getHealth()
      .then(d => {
        if (!d.initialized) {
          setResult(null);
          try { localStorage.removeItem(STORAGE_KEY); } catch { /* ignore */ }
        }
      })
      .catch(() => null);
  }, []);

  const handleLoadFromHistory = async (filename: string) => {
    setLoadingHistory(filename);
    setError(null);
    try {
      const resp = await api.refreshSystem();
      setResult({
        status: "completed",
        system_refreshed: true,
        total_accounts: resp.accounts as number,
        total_transactions: resp.transactions as number,
      });
      setTimeout(() => { window.location.href = "/"; }, 1500);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load system from database");
    } finally {
      setLoadingHistory(null);
    }
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const f = e.dataTransfer.files[0];
    if (f && f.name.endsWith(".csv")) { setFile(f); setError(null); }
    else setError("Please upload a CSV file");
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) { setFile(f); setError(null); }
  };

  const handleSubmit = async () => {
    if (!file) { setError("Please select a CSV file to upload"); return; }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.ingestUpload(file, date || undefined, force) as unknown as IngestionResult;
      setResult(res);
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(res)); } catch { /* ignore */ }
      loadHistory();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ingestion failed");
    } finally {
      setLoading(false);
    }
  };

  const priorityAccounts = result?.priority_accounts ?? [];
  const profileMismatches = result?.profile_mismatches ?? [];
  const PRIORITY_PER_PAGE = 3;
  const PROFILE_PER_PAGE = 5;
  const prioritySlice = priorityAccounts.slice(priorityPage * PRIORITY_PER_PAGE, (priorityPage + 1) * PRIORITY_PER_PAGE);
  const profileSlice = profileMismatches.slice(profilePage * PROFILE_PER_PAGE, (profilePage + 1) * PROFILE_PER_PAGE);

  return (
    <div className="min-h-screen bg-[#0b1120] p-6 text-white max-w-[1400px] mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <span className="text-3xl">📥</span> TraceX — EOD Transaction Ingestion
            <InfoTooltip text="End-of-Day (EOD) Ingestion processes your daily transaction CSV export. Each upload appends to cumulative data — graph, ML scores, and AML detectors run on the full dataset after every upload." />
          </h1>
          <p className="text-sm text-slate-400 mt-1">Upload daily transaction CSV to detect fraud patterns on your cumulative dataset</p>
        </div>
        <button onClick={loadHistory} className="px-3 py-1.5 rounded-lg bg-slate-800 text-xs text-slate-300 hover:bg-slate-700 border border-slate-700">
          View History
        </button>
      </div>

      {/* Upload Card */}
      <Card>
        <div className="p-6 space-y-5">
          <h2 className="text-lg font-semibold text-white">Upload Transaction CSV</h2>
          <p className="text-xs text-slate-400">
            Supports IBM AML format or normalized CSV (timestamp, source_account, dest_account, amount). Each upload is appended — existing transactions are never duplicated.
          </p>

          {/* Drag & Drop */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-all ${
              dragActive ? "border-blue-500 bg-blue-500/10"
              : file ? "border-emerald-500/50 bg-emerald-500/5"
              : "border-slate-700 hover:border-slate-500 bg-slate-900/50"
            }`}
          >
            <input ref={inputRef} type="file" accept=".csv" onChange={handleFileChange} className="hidden" />
            {file ? (
              <div className="space-y-2">
                <div className="text-4xl">✅</div>
                <p className="text-sm font-medium text-emerald-400">{file.name}</p>
                <p className="text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB · Click or drop to replace</p>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="text-4xl">📄</div>
                <p className="text-sm text-slate-300">Drag & drop your CSV file here</p>
                <p className="text-xs text-slate-500">or click to browse</p>
              </div>
            )}
          </div>

          {/* Options */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Ingestion Date (optional)
                <InfoTooltip text="Business date for this file. Defaults to today. Used for 7-day rolling window detection." />
              </label>
              <input
                type="date" value={date} onChange={(e) => setDate(e.target.value)}
                className="w-full rounded-lg bg-slate-800 border border-slate-700 px-3 py-2 text-sm text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} className="rounded bg-slate-800 border-slate-700 text-blue-500 focus:ring-blue-500" />
                <span className="text-xs text-slate-400">
                  Force re-process
                  <InfoTooltip text="Skip duplicate check. Use if detection parameters changed since last upload." />
                </span>
              </label>
            </div>
            <div className="flex items-end justify-end">
              <button
                onClick={handleSubmit}
                disabled={!file || loading}
                className={`px-6 py-2.5 rounded-lg font-medium text-sm transition-all ${
                  !file || loading ? "bg-slate-700 text-slate-500 cursor-not-allowed"
                  : "bg-blue-600 text-white hover:bg-blue-500 shadow-lg shadow-blue-600/20"
                }`}
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Processing...
                  </span>
                ) : "🚀 Process & Analyze"}
              </button>
            </div>
          </div>
        </div>
      </Card>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
          <p className="text-sm text-red-400">❌ {error}</p>
        </div>
      )}

      {/* Loading */}
      {loading && (
        <Card>
          <div className="p-8 text-center space-y-3">
            <div className="h-8 w-8 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin mx-auto" />
            <p className="text-sm text-slate-300">Processing transactions...</p>
            <p className="text-xs text-slate-500">Running fraud detection, pattern analysis, and risk scoring on cumulative dataset</p>
          </div>
        </Card>
      )}

      {/* Skipped */}
      {result && result.status === "skipped" && (
        <Card>
          <div className="p-6 space-y-3">
            <h2 className="text-lg font-semibold text-yellow-400">⏭️ Ingestion Skipped (Duplicate)</h2>
            <p className="text-sm text-slate-400">This file was already processed. Enable &quot;Force re-process&quot; to ingest again.</p>
          </div>
        </Card>
      )}

      {/* ── Results ── */}
      {result && result.status === "completed" && (
        <div className="space-y-5">

          {/* Stats Row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Transactions", value: result.total_transactions?.toLocaleString() ?? "—", color: "text-white" },
              { label: "New Accounts", value: result.new_accounts?.toLocaleString() ?? "—", color: "text-emerald-400" },
              { label: "Alerts Generated", value: result.alerts_generated?.toLocaleString() ?? "—", color: "text-red-400" },
              { label: "Processing Time", value: result.processing_time_sec ? `${result.processing_time_sec}s` : "—", color: "text-blue-400" },
            ].map(({ label, value, color }) => (
              <Card key={label}>
                <div className="p-4">
                  <p className="text-xs text-slate-500">{label}</p>
                  <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
                </div>
              </Card>
            ))}
          </div>

          {/* Section 1 — Mini Interactive Graph */}
          <Card>
            <div className="p-5">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold text-slate-300">
                  Transaction Network (This Upload)
                  <InfoTooltip text="Interactive graph of accounts and transactions from this upload. Node size reflects risk level. Click a node to highlight its connections." />
                </h3>
                {result.graph_data && (
                  <span className="text-xs text-slate-500">
                    {result.graph_data.nodes.length} nodes · {result.graph_data.edges.length} edges
                  </span>
                )}
              </div>
              {result.graph_data && result.graph_data.nodes.length > 0 ? (
                <div style={{ height: 400 }} className="w-full rounded-lg overflow-hidden border border-slate-700/50">
                  <CytoscapeGraph
                    data={result.graph_data}
                    layoutHint="cose"
                    className="w-full h-full"
                  />
                </div>
              ) : (
                <div className="h-[400px] flex items-center justify-center text-xs text-slate-500 border border-slate-700/50 rounded-lg">
                  Graph data unavailable
                </div>
              )}
            </div>
          </Card>

          {/* Section 2 — Priority Investigation Queue */}
          <Card>
            <div className="p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-3">
                Priority Investigation Queue (This Upload)
                <InfoTooltip text="Accounts from the uploaded CSV ranked by risk score. Priority computed from risk level, confidence, and transaction volume." />
              </h3>
              {priorityAccounts.length > 0 ? (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-slate-700">
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">Account ID</th>
                          <th className="text-right py-2 px-3 text-slate-500 font-medium">Risk Score</th>
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">Risk Level</th>
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">Priority</th>
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">Role</th>
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">Patterns</th>
                          <th className="text-right py-2 px-3 text-slate-500 font-medium">Inflow</th>
                          <th className="text-right py-2 px-3 text-slate-500 font-medium">Outflow</th>
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">AI Brief</th>
                        </tr>
                      </thead>
                      <tbody>
                        {prioritySlice.map((acc, i) => (
                          <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/40">
                            <td className="py-2.5 px-3 font-mono text-blue-400">{acc.account_id}</td>
                            <td className="py-2.5 px-3 text-right font-bold text-white">{acc.risk_score.toFixed(1)}</td>
                            <td className="py-2.5 px-3">
                              <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${RISK_BADGE[acc.risk_level] ?? RISK_BADGE.LOW}`}>
                                {acc.risk_level}
                              </span>
                            </td>
                            <td className="py-2.5 px-3">
                              <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${PRIORITY_BADGE[acc.priority] ?? PRIORITY_BADGE.P4}`}>
                                {acc.priority}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 text-slate-400">{acc.role}</td>
                            <td className="py-2.5 px-3">
                              <div className="flex flex-wrap gap-1">
                                {acc.patterns.slice(0, 3).map(p => (
                                  <span key={p} className="px-1.5 py-0.5 rounded-full bg-orange-500/10 border border-orange-500/30 text-[9px] text-orange-400">{p}</span>
                                ))}
                                {acc.patterns.length > 3 && <span className="text-[9px] text-slate-500">+{acc.patterns.length - 3}</span>}
                              </div>
                            </td>
                            <td className="py-2.5 px-3 text-right text-emerald-400">{fmt(acc.total_inflow)}</td>
                            <td className="py-2.5 px-3 text-right text-red-400">{fmt(acc.total_outflow)}</td>
                            <td className="py-2.5 px-3">
                              <AIExplanationPanel accountId={acc.account_id} />
                              <button
                                onClick={() => openValidation(acc.account_id)}
                                className="mt-1.5 inline-flex items-center gap-1 px-2 py-0.5 rounded bg-blue-600/20 border border-blue-500/30 text-[10px] text-blue-300 hover:bg-blue-600/30 transition-colors"
                              >
                                🕸️ Graph Validation
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Paginator page={priorityPage} total={priorityAccounts.length} perPage={PRIORITY_PER_PAGE} onChange={setPriorityPage} />
                </>
              ) : (
                <p className="text-xs text-slate-500">No risk accounts identified</p>
              )}
            </div>
          </Card>

          {/* Section 3 — Channel Distribution */}
          <Card>
            <div className="p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-3">
                Channel Distribution (This Upload)
                <InfoTooltip text="Transaction count per payment channel in the uploaded CSV." />
              </h3>
              {result.channel_distribution && result.channel_distribution.length > 0 ? (
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={result.channel_distribution} layout="vertical" margin={{ top: 0, right: 20, left: 10, bottom: 0 }}>
                    <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} />
                    <YAxis dataKey="channel" type="category" tick={{ fontSize: 10, fill: "#94a3b8" }} width={100} />
                    <Tooltip
                      contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "8px", fontSize: "12px" }}
                      formatter={(v: unknown) => [(v as number).toLocaleString(), "Transactions"]}
                    />
                    <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="h-[200px] flex items-center justify-center text-xs text-slate-500">No channel data</div>
              )}
            </div>
          </Card>

          {/* Section 3b — Patterns Detected */}
          {result.patterns_detected && Object.keys(result.patterns_detected).length > 0 && (
            <Card>
              <div className="p-5">
                <h3 className="text-sm font-semibold text-slate-300 mb-3">
                  Fraud Patterns Detected (This Upload)
                  <InfoTooltip text="AML typologies detected by the pattern engine during EOD ingestion of this CSV." />
                </h3>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={Object.entries(result.patterns_detected).map(([name, count]) => ({ name, count }))}
                    layout="vertical" margin={{ top: 0, right: 20, left: 20, bottom: 0 }}>
                    <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} />
                    <YAxis dataKey="name" type="category" tick={{ fontSize: 10, fill: "#94a3b8" }} width={120} />
                    <Tooltip contentStyle={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 8, fontSize: 11 }}
                      cursor={{ fill: "rgba(249,115,22,0.08)" }} />
                    <Bar dataKey="count" fill="#f97316" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
          )}

          {/* Section 4 — Profile Mismatches */}
          <Card>
            <div className="p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-3">
                Profile Mismatches (This Upload)
                <InfoTooltip text="Accounts whose actual transaction volume significantly exceeds their declared annual income — a key AML indicator." />
              </h3>
              {profileMismatches.length > 0 ? (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-slate-700">
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">Account ID</th>
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">Occupation</th>
                          <th className="text-right py-2 px-3 text-slate-500 font-medium">Declared Income</th>
                          <th className="text-right py-2 px-3 text-slate-500 font-medium">Actual Volume</th>
                          <th className="text-right py-2 px-3 text-slate-500 font-medium">Ratio</th>
                          <th className="text-right py-2 px-3 text-slate-500 font-medium">Risk Score</th>
                          <th className="text-left py-2 px-3 text-slate-500 font-medium">AI Brief</th>
                        </tr>
                      </thead>
                      <tbody>
                        {profileSlice.map((pm, i) => (
                          <tr key={i} className={`border-b border-slate-800 ${i % 2 === 0 ? "bg-slate-900/20" : ""} hover:bg-slate-800/40`}>
                            <td className="py-2.5 px-3 font-mono text-blue-400">{pm.account_id}</td>
                            <td className="py-2.5 px-3 text-slate-300">{pm.occupation}</td>
                            <td className="py-2.5 px-3 text-right text-slate-400">{fmt(pm.declared_income)}</td>
                            <td className="py-2.5 px-3 text-right text-slate-300">{fmt(pm.actual_volume)}</td>
                            <td className={`py-2.5 px-3 text-right font-bold ${ratioColor(pm.ratio)}`}>{pm.ratio.toFixed(1)}×</td>
                            <td className="py-2.5 px-3 text-right text-white font-medium">{pm.risk_score.toFixed(1)}</td>
                            <td className="py-2.5 px-3">
                              <AIExplanationPanel accountId={pm.account_id} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Paginator page={profilePage} total={profileMismatches.length} perPage={PROFILE_PER_PAGE} onChange={setProfilePage} />
                </>
              ) : (
                <p className="text-xs text-slate-500">No income mismatches detected — accounts may lack income profile data</p>
              )}
            </div>
          </Card>

          {/* Section 5 — Speed Alerts */}
          <Card>
            <div className="p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-3">
                Top Speed Alerts (This Upload)
                <InfoTooltip text="Accounts with the highest transaction velocity in this CSV — potential smurfing or rapid layering behaviour." />
              </h3>
              {result.speed_alerts && result.speed_alerts.length > 0 ? (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-700">
                      <th className="text-left py-2 px-3 text-slate-500 font-medium">Account ID</th>
                      <th className="text-right py-2 px-3 text-slate-500 font-medium">Transactions</th>
                      <th className="text-left py-2 px-3 text-slate-500 font-medium">Risk Level</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.speed_alerts.map((sa, i) => (
                      <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/40">
                        <td className="py-2.5 px-3 font-mono text-blue-400">{sa.account_id}</td>
                        <td className="py-2.5 px-3 text-right font-bold text-white">{sa.txn_count.toLocaleString()}</td>
                        <td className="py-2.5 px-3">
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${RISK_BADGE[sa.risk_level] ?? RISK_BADGE.LOW}`}>
                            {sa.risk_level}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-xs text-slate-500">No speed alerts</p>
              )}
            </div>
          </Card>

          {/* Section 6 — CSV Preview */}
          <Card>
            <div className="p-5">
              <h3 className="text-sm font-semibold text-slate-300 mb-3">CSV Preview (First 20 Rows)</h3>
              {result.row_preview && result.row_preview.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-slate-700">
                        {["txn_id", "timestamp", "source_account", "dest_account", "amount", "channel", "occupation", "declared_income"].map(col => (
                          <th key={col} className="text-left py-2 px-2 text-slate-500 font-medium whitespace-nowrap">{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.row_preview.map((row, i) => (
                        <tr key={i} className={`border-b border-slate-800 ${i % 2 === 0 ? "bg-slate-900/30" : ""}`}>
                          <td className="py-1.5 px-2 font-mono text-slate-400">{truncate(String(row.txn_id ?? "—"), 16)}</td>
                          <td className="py-1.5 px-2 text-slate-400 whitespace-nowrap">{truncate(String(row.timestamp ?? "—"), 20)}</td>
                          <td className="py-1.5 px-2 font-mono text-blue-400">{truncate(String(row.source_account ?? "—"))}</td>
                          <td className="py-1.5 px-2 font-mono text-purple-400">{truncate(String(row.dest_account ?? "—"))}</td>
                          <td className="py-1.5 px-2 text-right text-slate-300">₹{Number(row.amount ?? 0).toLocaleString()}</td>
                          <td className="py-1.5 px-2 text-slate-400">{String(row.channel ?? "—")}</td>
                          <td className="py-1.5 px-2 text-slate-400 whitespace-nowrap">{row.occupation ?? "—"}</td>
                          <td className="py-1.5 px-2 text-right text-slate-300 whitespace-nowrap">{row.declared_annual_income != null ? fmt(Number(row.declared_annual_income)) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-slate-500">No preview available</p>
              )}
            </div>
          </Card>

          {/* System refresh status */}
          {result.system_refreshed !== undefined && (
            <div className={`rounded-lg p-3 text-xs ${result.system_refreshed ? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400" : "bg-yellow-500/10 border border-yellow-500/20 text-yellow-400"}`}>
              {result.system_refreshed
                ? "✅ All views updated with cumulative data — graph, anomaly queue, and patterns reflect the full dataset."
                : `⚠️ Data ingested to DB but in-memory views need manual refresh. ${result.refresh_warning ?? ""}`}
            </div>
          )}

          {/* Section 7 — Navigation */}
          <div className="flex flex-wrap gap-3 pt-1">
            <Link href="/" className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors">
              📊 Go to Dashboard →
            </Link>
            <Link href="/graph" className="px-3 py-2 rounded-lg bg-purple-600/20 border border-purple-500/30 text-xs text-purple-400 hover:bg-purple-600/30 transition-colors">🔍 Graph Explorer</Link>
            <Link href="/anomaly" className="px-3 py-2 rounded-lg bg-red-600/20 border border-red-500/30 text-xs text-red-400 hover:bg-red-600/30 transition-colors">⚠️ Investigation Queue</Link>
            <Link href="/patterns" className="px-3 py-2 rounded-lg bg-orange-600/20 border border-orange-500/30 text-xs text-orange-400 hover:bg-orange-600/30 transition-colors">🔄 Pattern Detector</Link>
            <Link href="/evidence" className="px-3 py-2 rounded-lg bg-green-600/20 border border-green-500/30 text-xs text-green-400 hover:bg-green-600/30 transition-colors">📋 Generate STR</Link>
          </div>

        </div>
      )}

      {/* Ingestion History */}
      {history && (
        <Card>
          <div className="p-6 space-y-3">
            <h2 className="text-lg font-semibold text-white">📜 Ingestion History</h2>
            {history.length === 0 ? (
              <p className="text-sm text-slate-500">No previous ingestions found.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-700">
                      <th className="text-left py-2 px-2 text-slate-500 font-medium">File <InfoTooltip text="Filename of the uploaded CSV. Duplicate prevention uses SHA-256 file hash." /></th>
                      <th className="text-left py-2 px-2 text-slate-500 font-medium">Date</th>
                      <th className="text-left py-2 px-2 text-slate-500 font-medium">Transactions <InfoTooltip text="Number of transaction records in this file." /></th>
                      <th className="text-left py-2 px-2 text-slate-500 font-medium">Accounts</th>
                      <th className="text-left py-2 px-2 text-slate-500 font-medium">Status <InfoTooltip text="completed = processed. skipped = duplicate detected." /></th>
                      <th className="text-left py-2 px-2 text-slate-500 font-medium">Processed At</th>
                      <th className="text-left py-2 px-2 text-slate-500 font-medium">Actions <InfoTooltip text="Rebuild in-memory state from all DB data. Use after server restart." /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((item, idx) => {
                      const filename = String(item.filename ?? "");
                      const isLoading = loadingHistory === filename;
                      return (
                        <tr key={idx} className="border-b border-slate-800 hover:bg-slate-800/50">
                          <td className="py-2 px-2 text-slate-300">{filename || "—"}</td>
                          <td className="py-2 px-2 text-slate-400">{String(item.ingestion_date ?? "—")}</td>
                          <td className="py-2 px-2 text-slate-300">{Number(item.num_transactions ?? 0).toLocaleString()}</td>
                          <td className="py-2 px-2 text-slate-300">{Number(item.num_accounts ?? 0).toLocaleString()}</td>
                          <td className="py-2 px-2">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${item.status === "completed" ? "bg-emerald-500/20 text-emerald-400" : "bg-yellow-500/20 text-yellow-400"}`}>
                              {String(item.status ?? "unknown")}
                            </span>
                          </td>
                          <td className="py-2 px-2 text-slate-500">{String(item.created_at ?? "—")}</td>
                          <td className="py-2 px-2">
                            <button
                              onClick={() => handleLoadFromHistory(filename)}
                              disabled={isLoading}
                              className={`px-2 py-1 rounded text-[10px] font-medium transition-all ${isLoading ? "bg-blue-600/30 text-blue-300 cursor-wait" : "bg-blue-600/20 border border-blue-500/30 text-blue-400 hover:bg-blue-600/40"}`}
                            >
                              {isLoading ? "Loading..." : "🔄 Load & Analyze"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* How It Works */}
      <Card>
        <div className="p-6 space-y-3">
          <h2 className="text-sm font-semibold text-slate-300">ℹ️ How It Works</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-400">
            <div className="space-y-1">
              <p className="font-medium text-white">1. Upload CSV <InfoTooltip text="Required: timestamp, source_account, dest_account, amount. Column names are detected automatically." /></p>
              <p>Upload your end-of-day transaction dump. Each upload appends to the existing dataset — no data is replaced.</p>
            </div>
            <div className="space-y-1">
              <p className="font-medium text-white">2. Incremental Analysis <InfoTooltip text="New accounts scored on today's data. Existing accounts use 7-day rolling window. Duplicate transactions are skipped via txn_id." /></p>
              <p>New accounts analyzed on today&apos;s data. Existing accounts use 7-day rolling window. Graph and ML run on all accumulated data.</p>
            </div>
            <div className="space-y-1">
              <p className="font-medium text-white">3. Updated Results <InfoTooltip text="After ingestion all views update: Graph (cumulative edges), Anomaly Queue (rescored on full dataset), Patterns (re-run), Profile Analyzer (updated volumes)." /></p>
              <p>All dashboards reflect the cumulative dataset. Each upload grows your network view and improves detection accuracy.</p>
            </div>
          </div>
        </div>
      </Card>

      <GraphValidationDialog
        accountId={validationAccountId}
        open={validationOpen}
        onClose={() => setValidationOpen(false)}
      />

    </div>
  );
}
