"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import dynamic from "next/dynamic";
import {
  api,
  API_BASE,
  GraphData,
  GraphNode,
  RealtimeSSEEvent,
  RealtimeTransactionPayload,
  RealtimeAlertPayload,
} from "@/lib/api";
import { Card, InfoTooltip } from "@/components/ui";
import { formatINR } from "@/lib/utils";

const CytoscapeGraph = dynamic(() => import("@/components/CytoscapeGraph"), { ssr: false });

type RunStatus = "idle" | "running" | "complete";

interface AlertRow extends RealtimeAlertPayload {
  _key: string;
}

const PATTERN_BADGE: Record<string, string> = {
  structuring: "bg-red-500/20 text-red-400 border border-red-500/30",
  round_trip: "bg-red-500/20 text-red-400 border border-red-500/30",
  fan_in: "bg-orange-500/20 text-orange-400 border border-orange-500/30",
  fan_out: "bg-orange-500/20 text-orange-400 border border-orange-500/30",
  profile_mismatch: "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30",
};

function patternBadgeClass(pattern: string): string {
  return PATTERN_BADGE[pattern] ?? "bg-slate-600/30 text-slate-300 border border-slate-500/40";
}

function upsertNode(nodes: GraphNode[], id: string): GraphNode[] {
  if (!id || nodes.some((n) => n.id === id)) return nodes;
  return [...nodes, { id, risk_score: 5, risk_level: "LOW", risk_color: "#22c55e", role: "NORMAL" }];
}

function addTransactionToGraph(prev: GraphData, txn: RealtimeTransactionPayload): GraphData {
  let nodes = upsertNode(prev.nodes, txn.source_account);
  nodes = upsertNode(nodes, txn.dest_account);
  if (!txn.source_account || !txn.dest_account) return { ...prev, nodes };
  return {
    nodes,
    edges: [
      ...prev.edges,
      {
        source: txn.source_account,
        target: txn.dest_account,
        amount: txn.amount,
        channel: txn.payment_format,
        timestamp: txn.timestamp,
      },
    ],
  };
}

function flagNodesForAlert(prev: GraphData, alert: RealtimeAlertPayload): GraphData {
  const flagIds = new Set([alert.source_account, alert.dest_account]);
  return {
    ...prev,
    nodes: prev.nodes.map((n) =>
      flagIds.has(n.id)
        ? { ...n, risk_level: "CRITICAL", risk_score: 92, risk_color: "#ef4444" }
        : n
    ),
  };
}

function fmtElapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function RealtimePage() {
  const [status, setStatus] = useState<RunStatus>("idle");
  const [processed, setProcessed] = useState(0);
  const [total, setTotal] = useState(0);
  const [transactions, setTransactions] = useState<RealtimeTransactionPayload[]>([]);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], edges: [] });
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [flashKey, setFlashKey] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startTimer = useCallback(() => {
    stopTimer();
    startTimeRef.current = Date.now();
    setElapsed(0);
    timerRef.current = setInterval(() => {
      setElapsed((Date.now() - startTimeRef.current) / 1000);
    }, 250);
  }, [stopTimer]);

  const closeStream = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  useEffect(() => {
    // Cleanup on unmount
    return () => {
      closeStream();
      stopTimer();
      if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
    };
  }, [closeStream, stopTimer]);

  const attachStream = useCallback(() => {
    closeStream();
    const es = new EventSource(`${API_BASE}/api/realtime/stream`);
    esRef.current = es;

    es.onmessage = (ev) => {
      let parsed: RealtimeSSEEvent;
      try {
        parsed = JSON.parse(ev.data);
      } catch {
        return;
      }

      if (parsed.topic === "realtime.transaction") {
        const d = parsed.data;
        setProcessed(d.processed);
        setTotal(d.total);
        setTransactions((prev) => [d, ...prev]);
        setGraphData((prev) => addTransactionToGraph(prev, d));
      } else if (parsed.topic === "realtime.alert") {
        const d = parsed.data;
        setProcessed(d.processed);
        setTotal(d.total);
        const key = `${d.pattern_type}-${d.processed}-${d.timestamp}`;
        setAlerts((prev) => [{ ...d, _key: key }, ...prev]);
        setGraphData((prev) => flagNodesForAlert(prev, d));
        setFlashKey(key);
        if (flashTimeoutRef.current) clearTimeout(flashTimeoutRef.current);
        flashTimeoutRef.current = setTimeout(() => setFlashKey(null), 1800);
      } else if (parsed.topic === "realtime.done") {
        setStatus("complete");
        stopTimer();
        closeStream();
      }
    };

    es.onerror = () => {
      // The backend closes the stream cleanly after realtime.done (via our own
      // closeStream() above), which never fires onerror. Reaching here means the
      // connection genuinely dropped (server down, network blip, etc). EventSource
      // would otherwise keep silently retrying forever, so stop it, surface the
      // failure, and let the user restart explicitly.
      closeStream();
      stopTimer();
      setStatus((s) => (s === "running" ? "idle" : s));
      setError("Lost connection to the live stream. Click Start Real-Time Demo to retry.");
    };
  }, [closeStream, stopTimer]);

  const handleStart = async () => {
    setError(null);
    setTransactions([]);
    setAlerts([]);
    setGraphData({ nodes: [], edges: [] });
    setProcessed(0);
    try {
      const res = await api.startRealtimeDemo();
      setTotal(res.total);
      setStatus("running");
      startTimer();
      attachStream();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to start demo";
      if (msg.includes("409")) {
        setError("A demo run is already in progress — attaching to the live stream instead.");
        setStatus("running");
        startTimer();
        // Fetch current progress immediately so the bar/counters aren't blank
        // until the next SSE event arrives (fallback from the plan's design).
        try {
          const st = await api.getRealtimeStatus();
          setProcessed(st.processed);
          setTotal(st.total);
        } catch {
          // Non-fatal — the next SSE event will populate these anyway.
        }
        attachStream();
      } else {
        setError(msg);
      }
    }
  };

  const progressPct = total > 0 ? Math.min(100, (processed / total) * 100) : 0;

  return (
    <div className="min-h-screen bg-[#0b1120] p-6 text-white max-w-[1400px] mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <span className="text-3xl">⚡</span> TraceX — Real-Time Fraud Detection
            <InfoTooltip text="Live streaming inference demo — watch transactions get analyzed and alerts raised in real time as each row is replayed through the real detection pipeline." />
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Live streaming inference demo — watch transactions get analyzed and alerts raised in real time
          </p>
        </div>
        <button
          onClick={handleStart}
          disabled={status === "running"}
          className={`px-6 py-2.5 rounded-lg font-medium text-sm transition-all ${
            status === "running"
              ? "bg-slate-700 text-slate-500 cursor-not-allowed"
              : "bg-blue-600 text-white hover:bg-blue-500 shadow-lg shadow-blue-600/20"
          }`}
        >
          {status === "running" ? (
            <span className="flex items-center gap-2">
              <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Running...
            </span>
          ) : status === "complete" ? (
            "🔁 Run Again"
          ) : (
            "▶ Start Real-Time Demo"
          )}
        </button>
      </div>

      {/* Error / info banner */}
      {error && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 p-4">
          <p className="text-sm text-yellow-400">⚠️ {error}</p>
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Transactions Processed", value: total > 0 ? `${processed} / ${total}` : "—", color: "text-white" },
          { label: "Alerts Raised", value: alerts.length.toLocaleString(), color: "text-red-400" },
          { label: "Elapsed Time", value: fmtElapsed(elapsed), color: "text-blue-400" },
          {
            label: "Status",
            value: status === "idle" ? "Idle" : status === "running" ? "Running" : "Complete",
            color: status === "running" ? "text-emerald-400" : status === "complete" ? "text-blue-400" : "text-slate-400",
          },
        ].map(({ label, value, color }) => (
          <Card key={label}>
            <div className="p-4">
              <p className="text-xs text-slate-500">{label}</p>
              <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
            </div>
          </Card>
        ))}
      </div>

      {/* Progress bar */}
      <Card>
        <div className="p-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-300">
              Replay Progress
              <InfoTooltip text="Each demo run replays 18 transactions through the real ingestion and detection pipeline, roughly 1.2 seconds apart." />
            </h3>
            <span className="text-xs text-slate-500">{processed} / {total || 18} transactions processed</span>
          </div>
          <div className="w-full h-2.5 rounded-full bg-slate-800 overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-blue-600 to-emerald-500 transition-all duration-500 ease-out"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      </Card>

      {/* Live Network Graph */}
      <Card>
        <div className="p-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold text-slate-300">
              Live Transaction Network
              <InfoTooltip text="Grows live as each transaction event arrives. Nodes flagged by an alert are recolored CRITICAL (red)." />
            </h3>
            <span className="text-xs text-slate-500">
              {graphData.nodes.length} nodes · {graphData.edges.length} edges
            </span>
          </div>
          {graphData.nodes.length > 0 ? (
            <div style={{ height: 400 }} className="w-full rounded-lg overflow-hidden border border-slate-700/50">
              <CytoscapeGraph data={graphData} layoutHint="cose" className="w-full h-full" />
            </div>
          ) : (
            <div className="h-[400px] flex items-center justify-center text-xs text-slate-500 border border-slate-700/50 rounded-lg">
              {status === "idle" ? "Start the demo to watch the network build live" : "Waiting for first transaction..."}
            </div>
          )}
        </div>
      </Card>

      {/* Live Alerts Panel */}
      <Card>
        <div className="p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-3">
            Live Alerts
            <InfoTooltip text="Alerts raised by the real AML pattern engine as each transaction is ingested. Newest first." />
          </h3>
          {alerts.length > 0 ? (
            <div className="space-y-2">
              {alerts.map((a) => (
                <div
                  key={a._key}
                  className={`rounded-lg border p-3 transition-all duration-700 ${
                    flashKey === a._key
                      ? "border-red-400 bg-red-500/20 scale-[1.01] shadow-lg shadow-red-500/20"
                      : "border-slate-700/50 bg-slate-900/40"
                  }`}
                >
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${patternBadgeClass(a.pattern_type)}`}>
                        {a.pattern_type.replace(/_/g, " ")}
                      </span>
                      <span className="text-xs font-mono text-blue-400">{a.source_account}</span>
                      <span className="text-slate-600 text-xs">→</span>
                      <span className="text-xs font-mono text-purple-400">{a.dest_account}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-slate-400">
                      <span className="text-white font-medium">{formatINR(a.amount)}</span>
                      <span className="text-slate-500">{a.timestamp}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              {status === "idle" ? "No alerts yet — start the demo to see live detections" : "No alerts yet — watching for patterns..."}
            </p>
          )}
        </div>
      </Card>

      {/* Live Transaction Feed */}
      <Card>
        <div className="p-5">
          <h3 className="text-sm font-semibold text-slate-300 mb-3">
            Live Transaction Feed
            <InfoTooltip text="Each row is processed through the real incremental detection pipeline as it streams in. Newest first." />
          </h3>
          {transactions.length > 0 ? (
            <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-[#111827]">
                  <tr className="border-b border-slate-700">
                    <th className="text-left py-2 px-3 text-slate-500 font-medium">Timestamp</th>
                    <th className="text-left py-2 px-3 text-slate-500 font-medium">Source</th>
                    <th className="text-left py-2 px-3 text-slate-500 font-medium">Dest</th>
                    <th className="text-right py-2 px-3 text-slate-500 font-medium">Amount</th>
                    <th className="text-left py-2 px-3 text-slate-500 font-medium">Channel</th>
                    <th className="text-right py-2 px-3 text-slate-500 font-medium">#</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((t, i) => (
                    <tr key={`${t.processed}-${i}`} className={`border-b border-slate-800 ${t.alerts_generated > 0 ? "bg-red-500/5" : ""} hover:bg-slate-800/40`}>
                      <td className="py-2 px-3 text-slate-400 whitespace-nowrap">{t.timestamp}</td>
                      <td className="py-2 px-3 font-mono text-blue-400">{t.source_account}</td>
                      <td className="py-2 px-3 font-mono text-purple-400">{t.dest_account}</td>
                      <td className="py-2 px-3 text-right text-slate-300">{formatINR(t.amount)}</td>
                      <td className="py-2 px-3 text-slate-400">{t.payment_format}</td>
                      <td className="py-2 px-3 text-right text-slate-500">{t.processed}/{t.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-slate-500">
              {status === "idle" ? "No transactions yet — start the demo to see live processing" : "Waiting for first transaction..."}
            </p>
          )}
        </div>
      </Card>

      {/* How It Works */}
      <Card>
        <div className="p-6 space-y-3">
          <h2 className="text-sm font-semibold text-slate-300">ℹ️ How It Works</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs text-slate-400">
            <div className="space-y-1">
              <p className="font-medium text-white">1. Start Stream</p>
              <p>Kicks off a server-side replay of 18 demo transactions, spaced roughly 1.2 seconds apart, through the real ingestion pipeline.</p>
            </div>
            <div className="space-y-1">
              <p className="font-medium text-white">2. Live Detection</p>
              <p>Each row is scored by the real AML pattern engine as it arrives — no pre-computed results. Alerts appear the moment a pattern is confirmed.</p>
            </div>
            <div className="space-y-1">
              <p className="font-medium text-white">3. Live Visualization</p>
              <p>The network graph, alert feed, and transaction table update incrementally via Server-Sent Events as the run progresses.</p>
            </div>
          </div>
        </div>
      </Card>

    </div>
  );
}
