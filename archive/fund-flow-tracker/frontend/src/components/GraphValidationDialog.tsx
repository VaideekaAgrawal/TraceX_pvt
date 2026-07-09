"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { api, GraphValidationResponse } from "@/lib/api";
import { Loader, StatCard } from "@/components/ui";

const CytoscapeGraph = dynamic(() => import("@/components/CytoscapeGraph"), { ssr: false });

function fmtMs(n: number | undefined) {
  return n === undefined ? "—" : `${n.toFixed(1)} ms`;
}

export default function GraphValidationDialog({
  accountId,
  open,
  onClose,
}: {
  accountId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  // Keyed by accountId so `loading`/`data`/`error` can be *derived* below instead
  // of reset via synchronous setState calls at the top of the effect.
  const [result, setResult] = useState<{
    accountId: string;
    data: GraphValidationResponse | null;
    error: string | null;
  } | null>(null);

  // Fetch on open / accountId change
  useEffect(() => {
    if (!open || !accountId) return;
    let cancelled = false;
    api.getGraphValidation(accountId)
      .then((res) => { if (!cancelled) setResult({ accountId, data: res, error: null }); })
      .catch((err: unknown) => {
        if (!cancelled) {
          setResult({
            accountId,
            data: null,
            error: err instanceof Error ? err.message : "Failed to load graph validation",
          });
        }
      });
    return () => { cancelled = true; };
  }, [open, accountId]);

  const isCurrent = result !== null && accountId !== null && result.accountId === accountId;
  const data = isCurrent ? result.data : null;
  const error = isCurrent ? result.error : null;
  const loading = open && accountId !== null && !isCurrent;

  // Escape-to-close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open || !accountId) return null;

  const gv = data?.graph_validation;
  const fpGate = gv?.false_positive_gate;
  const runtimes = gv?.algorithm_runtime_ms ?? {};

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl max-h-[85vh] overflow-y-auto rounded-xl border border-slate-700/50 bg-[#111827] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-700/50 bg-[#111827] px-5 py-4">
          <h2 className="text-lg font-semibold text-white">
            Graph Validation — <span className="font-mono text-blue-400">{accountId}</span>
          </h2>
          <button
            onClick={onClose}
            aria-label="Close"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-800 hover:text-white transition-colors text-lg"
          >
            ✕
          </button>
        </div>

        <div className="p-5 space-y-5">
          {loading && <Loader />}

          {!loading && error && (
            <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4">
              <p className="text-sm text-red-400">❌ {error}</p>
            </div>
          )}

          {!loading && !error && data && (
            <>
              {/* Graph */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold text-slate-300">Transaction Network</h3>
                  <span className="text-xs text-slate-500">
                    {data.graph.nodes.length} nodes · {data.graph.edges.length} edges
                  </span>
                </div>
                {data.graph.nodes.length > 0 ? (
                  <div style={{ height: 380 }} className="w-full rounded-lg overflow-hidden border border-slate-700/50">
                    <CytoscapeGraph
                      data={data.graph}
                      egoMode
                      centerId={data.graph.center || accountId}
                      className="w-full h-full"
                    />
                  </div>
                ) : (
                  <div className="h-[380px] flex items-center justify-center text-xs text-slate-500 border border-slate-700/50 rounded-lg">
                    Graph data unavailable
                  </div>
                )}
              </div>

              {/* Algorithm validation stats */}
              {gv && (
                <div>
                  <h3 className="text-sm font-semibold text-slate-300 mb-3">Graph Algorithm Validation</h3>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                    <StatCard label="Nodes" value={gv.nodes} icon="⚫" color="blue" />
                    <StatCard label="Edges" value={gv.edges} icon="🔗" color="blue" />
                    <StatCard
                      label="Layering Chains"
                      value={gv.layering_chains_found}
                      sub={`shortest ${gv.shortest_chain} · longest ${gv.longest_chain}`}
                      icon="🔗"
                      color="orange"
                    />
                    <StatCard
                      label="Round-Trip Cycles"
                      value={gv.round_trip_cycles_found}
                      sub={`shortest ${gv.shortest_cycle} · longest ${gv.longest_cycle}`}
                      icon="🔄"
                      color="purple"
                    />
                    <StatCard label="Structuring Accounts" value={gv.structuring_accounts} icon="💰" color="yellow" />
                    <StatCard label="Dormant Activations" value={gv.dormant_activations} icon="💤" color="red" />
                    <StatCard label="Profile Mismatches" value={gv.profile_mismatches} icon="👤" color="orange" />
                    <StatCard
                      label="Centrality Cache"
                      value={gv.centrality_cache_hit ? "Hit" : "Miss"}
                      icon="⚡"
                      color={gv.centrality_cache_hit ? "green" : "yellow"}
                    />
                  </div>

                  {/* Algorithm runtimes */}
                  <div className="mt-3 rounded-lg border border-slate-700/50 bg-slate-900/40 p-3">
                    <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">Algorithm Runtimes</p>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {Object.entries(runtimes).map(([key, ms]) => (
                        <div key={key} className="flex flex-col">
                          <span className="text-[10px] text-slate-500">{key.replace(/_/g, " ")}</span>
                          <span className="text-sm font-mono text-white">{fmtMs(ms)}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* False-positive gate */}
                  {fpGate && (
                    <div className="mt-3">
                      <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
                        False-Positive Gate
                      </p>
                      <div className="grid grid-cols-3 gap-3">
                        <StatCard label="Single-Signal" value={fpGate.single_signal_accounts} color="yellow" />
                        <StatCard label="Multi-Signal" value={fpGate.multi_signal_accounts} color="orange" />
                        <StatCard
                          label="Promoted to P1"
                          value={fpGate.accounts_promoted_to_P1}
                          sub="P1 = flagged by 3+ independent signals"
                          color="red"
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Why flagged */}
              <div>
                <h3 className="text-sm font-semibold text-slate-300 mb-2">Why This Was Flagged</h3>
                <div className="rounded-lg bg-violet-500/5 border border-violet-500/20 p-4 text-sm text-slate-300 leading-relaxed">
                  🤖 {data.why_flagged || "No explanation available."}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
