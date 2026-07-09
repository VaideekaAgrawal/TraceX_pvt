"use client";

import { useEffect, useState } from "react";
import { api, RLQueueItem, RLStats } from "@/lib/api";
import { Card, StatCard, Loader, Badge, InfoTooltip } from "@/components/ui";
import { formatINR, getRiskBg, getRoleIcon } from "@/lib/utils";

export default function RLQueuePage() {
  const [queue, setQueue] = useState<RLQueueItem[]>([]);
  const [stats, setStats] = useState<RLStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [scenario, setScenario] = useState("layering_dominant");
  const [lastMessage, setLastMessage] = useState<string | null>(null);

  const load = () => {
    api
      .getRLQueue()
      .then((res) => {
        setQueue(res.queue);
        setStats(res.agent_stats);
        setError(null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load RL queue"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const submitFeedback = async (accountId: string, isTP: boolean) => {
    setBusyId(accountId);
    try {
      await api.submitRLFeedback(accountId, isTP);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to submit feedback");
    } finally {
      setBusyId(null);
    }
  };

  const runSimulation = async () => {
    setSimulating(true);
    try {
      const res = await api.simulateRL(30, scenario);
      setLastMessage(res.message);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Simulation failed");
    } finally {
      setSimulating(false);
    }
  };

  if (loading) return <Loader />;

  const maxWeight = Math.max(
    1e-6,
    ...(stats?.top_learned_features ?? []).map((f) => Math.abs(f.weight))
  );

  return (
    <div className="min-h-screen bg-[#0b1120] p-6 space-y-6 max-w-[1600px] mx-auto">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            🤖 RL-Ranked Investigation Queue
            <InfoTooltip text="A LinUCB contextual bandit re-ranks accounts by a UCB score (expected reward + exploration bonus). Every investigator verdict updates the agent online — no retraining, no GPU, fully interpretable." />
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Learns your bank&apos;s true-positive signal from every investigator decision
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
            className="text-xs rounded-md bg-slate-800 border border-slate-700 px-2 py-1.5 text-white focus:ring-1 focus:ring-blue-500"
          >
            <option value="layering_dominant">Scenario: Layering Dominant</option>
            <option value="balanced">Scenario: Balanced</option>
          </select>
          <button
            onClick={runSimulation}
            disabled={simulating}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-violet-600/20 border border-violet-500/30 text-xs text-violet-300 hover:bg-violet-600/30 transition-colors disabled:opacity-50"
          >
            {simulating ? (
              <span className="h-3 w-3 border border-violet-400/40 border-t-violet-400 rounded-full animate-spin" />
            ) : (
              <span>▶</span>
            )}
            Run Simulation (30 decisions)
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-500/10 border border-red-500/30 text-red-300 text-sm p-3">
          {error}
        </div>
      )}
      {lastMessage && (
        <div className="rounded-lg bg-violet-500/10 border border-violet-500/30 text-violet-200 text-sm p-3">
          {lastMessage}
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Agent Status" value={stats?.learning_status ?? "—"} icon="🧠" color="purple" />
        <StatCard label="Decisions Learned" value={stats?.total_feedback ?? 0} icon="📥" color="blue" />
        <StatCard
          label="Learned Precision"
          value={`${Math.round((stats?.learned_precision ?? 0) * 100)}%`}
          sub={`${stats?.tp_count ?? 0} TP / ${stats?.fp_count ?? 0} FP`}
          icon="🎯"
          color="green"
        />
        <StatCard label="Queue Size" value={queue.length} icon="📋" color="orange" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Queue Table */}
        <Card className="lg:col-span-2">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">
            Adaptive Queue<InfoTooltip text="Sorted by UCB score. (EXPL) marks accounts the agent is deliberately exploring due to high uncertainty — it hasn't seen enough similar cases yet." />
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 text-left text-xs text-slate-400 uppercase tracking-wider">
                  <th className="pb-3 pr-3">Account</th>
                  <th className="pb-3 pr-3">Risk</th>
                  <th className="pb-3 pr-3">RL Score</th>
                  <th className="pb-3 pr-3">Role</th>
                  <th className="pb-3 pr-3">Patterns</th>
                  <th className="pb-3 pr-3">Amount</th>
                  <th className="pb-3">Feedback</th>
                </tr>
              </thead>
              <tbody>
                {queue.map((item) => (
                  <tr
                    key={item.account_id}
                    className="border-b border-slate-700/30 hover:bg-slate-800/50 transition-colors"
                  >
                    <td className="py-3 pr-3 font-mono text-xs text-blue-400">{item.account_id}</td>
                    <td className="py-3 pr-3">
                      <span className={`inline-flex items-center rounded px-2 py-0.5 text-[10px] font-bold ${getRiskBg(item.risk_level)}`}>
                        {item.risk_score.toFixed(0)}
                      </span>
                    </td>
                    <td className="py-3 pr-3 text-xs text-slate-300">
                      {item.rl_ucb_score.toFixed(2)}
                      {item.rl_is_exploration && (
                        <span className="ml-1.5 text-[10px] text-amber-400" title="High uncertainty — agent is exploring">
                          (EXPL)
                        </span>
                      )}
                    </td>
                    <td className="py-3 pr-3 text-xs text-slate-300">
                      <span className="mr-1">{getRoleIcon(item.role)}</span>
                      {item.role}
                    </td>
                    <td className="py-3 pr-3">
                      <div className="flex flex-wrap gap-1">
                        {item.patterns.slice(0, 3).map((p) => (
                          <Badge key={p} variant="warning">{p}</Badge>
                        ))}
                        {item.patterns.length > 3 && (
                          <span className="text-[10px] text-slate-500">+{item.patterns.length - 3}</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3 pr-3 text-xs text-slate-300">{formatINR(item.total_amount)}</td>
                    <td className="py-3">
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => submitFeedback(item.account_id, true)}
                          disabled={busyId === item.account_id}
                          className="px-2 py-1 text-[10px] rounded bg-green-600/20 text-green-400 border border-green-500/30 hover:bg-green-600/30 disabled:opacity-50"
                        >
                          ✓ TP
                        </button>
                        <button
                          onClick={() => submitFeedback(item.account_id, false)}
                          disabled={busyId === item.account_id}
                          className="px-2 py-1 text-[10px] rounded bg-red-600/20 text-red-400 border border-red-500/30 hover:bg-red-600/30 disabled:opacity-50"
                        >
                          ✗ FP
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {queue.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-8 text-center text-xs text-slate-500">
                      No accounts in queue. Upload data via the Ingest page first.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>

        {/* Learned Weights Panel */}
        <Card>
          <h3 className="text-sm font-semibold text-slate-300 mb-1">
            Agent Learned Weights<InfoTooltip text="The bandit's linear weight vector, fully interpretable. Positive = increases priority. Negative = the agent learned this feature tends to be a false positive for this data." />
          </h3>
          <p className="text-xs text-slate-500 mb-3">Top 5 features by |weight|</p>
          <div className="space-y-3">
            {(stats?.top_learned_features ?? []).map((f) => {
              const isNeg = f.weight < 0;
              const width = (Math.abs(f.weight) / maxWeight) * 100;
              return (
                <div key={f.feature}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-slate-300">{f.feature}</span>
                    <span className={`text-xs ${isNeg ? "text-red-400" : "text-emerald-400"}`}>
                      {f.weight.toFixed(3)}
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${isNeg ? "bg-gradient-to-r from-red-600 to-red-400" : "bg-gradient-to-r from-emerald-600 to-emerald-400"}`}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                </div>
              );
            })}
            {(!stats || stats.total_feedback === 0) && (
              <p className="text-xs text-slate-600">
                Blank slate — no feedback yet. Run the simulation or submit TP/FP verdicts above.
              </p>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
