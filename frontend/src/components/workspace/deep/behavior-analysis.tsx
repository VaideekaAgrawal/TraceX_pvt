"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageField as Field, TriageSection } from "@/components/workspace/triage/triage-section";
import type { BehaviorAnalysisResponse } from "@/lib/api/types";

// Validated categorical palette (documented default slots 1/2 — blue/green)
// — same hexes the ROADMAP Phase 17 dataviz guidance names, used directly
// rather than through the Dashboard's placeholder `--chart-1..5` tokens
// (those are 0-chroma grays, not meant for real series identity here). This
// chart's own frozen 2-series theme, independent of the Investigation
// Graph's role palette (`graph-theme.css`) — no cross-surface collision
// concern since each surface owns its own legend.
const IN_COLOR = "#2a78d6";
const OUT_COLOR = "#008300";
const SINGLE_SERIES_COLOR = "#2a78d6";

// `deferred` -> plain-language label + explanation, matching `investigation/
// behavior_analysis.py`'s own documented reasoning for each gap. Rendered
// as "Not yet available," per this section's honesty-pattern requirement
// (same convention `customer-profile.tsx` uses for `omitted_fields`).
const DEFERRED_LABELS: Record<string, string> = {
  salary_mismatch: "Salary mismatch",
  seasonal_trends: "Seasonal trends",
};

function deferredLabel(field: string): string {
  return DEFERRED_LABELS[field] ?? field;
}

/**
 * L2 §6 — Historical Behaviour Analysis, `GET .../behavior` (ROADMAP Phase
 * 17). Renders the 5 real metrics (`investigation/behavior_analysis.py`);
 * the 2 `deferred` items render as "Not yet available," matching
 * `customer-profile.tsx`'s `omitted_fields` treatment — one honesty
 * convention across both sections, not two.
 */
export function BehaviorAnalysisSection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const { data, loading, error } = useTriageFetch<BehaviorAnalysisResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/behavior`,
  );

  return (
    <TriageSection
      title="Historical Behaviour Analysis"
      description="Monthly volume trends, cash/transfer patterns, dormancy reactivation, and velocity change for the primary account."
      loading={loading}
      error={error}
    >
      {data && (
        <div className="flex flex-col gap-6">
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Monthly Inflow vs. Outflow</p>
            {data.monthly_totals.length === 0 ? (
              <p className="text-muted-foreground text-sm">No monthly activity recorded.</p>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data.monthly_totals} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-border" />
                    <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} width={56} />
                    <Tooltip
                      formatter={(value, name) => [`₹${Number(value).toLocaleString()}`, name]}
                      contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--border)" }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Bar dataKey="total_in" name="Total In" fill={IN_COLOR} radius={[2, 2, 0, 0]} />
                    <Bar dataKey="total_out" name="Total Out" fill={OUT_COLOR} radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Cash Deposit Trend</p>
              {data.cash_deposit_trend.length === 0 ? (
                <p className="text-muted-foreground text-sm">No branch cash deposits recorded.</p>
              ) : (
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.cash_deposit_trend} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-border" />
                      <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} width={56} />
                      <Tooltip
                        formatter={(value) => [`₹${Number(value).toLocaleString()}`, "Cash deposits"]}
                        contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--border)" }}
                      />
                      <Bar dataKey="cash_deposit_total" fill={SINGLE_SERIES_COLOR} radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Transfer Trend</p>
              {data.transfer_trend.length === 0 ? (
                <p className="text-muted-foreground text-sm">No transfers recorded.</p>
              ) : (
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.transfer_trend} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-border" />
                      <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} width={56} />
                      <Tooltip
                        formatter={(value) => [`₹${Number(value).toLocaleString()}`, "Transfers"]}
                        contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid var(--border)" }}
                      />
                      <Bar dataKey="transfer_total" fill={SINGLE_SERIES_COLOR} radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>

          <div className="border-t pt-3">
            <p className="mb-2 text-xs font-medium text-muted-foreground">Transaction Velocity</p>
            <div className="flex flex-wrap items-center gap-6">
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
                <Field
                  label="Recent avg (weekly)"
                  value={data.velocity_increase.recent_avg_weekly_txn_count.toFixed(1)}
                />
                <Field
                  label="Baseline avg (weekly)"
                  value={data.velocity_increase.baseline_avg_weekly_txn_count.toFixed(1)}
                />
                <Field
                  label="Ratio"
                  value={data.velocity_increase.ratio != null ? `${data.velocity_increase.ratio.toFixed(2)}×` : "—"}
                />
              </dl>
              <Badge
                variant="outline"
                className={
                  data.velocity_increase.velocity_increase_detected
                    ? "border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400"
                    : "border-border text-muted-foreground"
                }
              >
                {data.velocity_increase.velocity_increase_detected
                  ? "Velocity increase detected"
                  : "No velocity increase detected"}
              </Badge>
            </div>
          </div>

          <div className="border-t pt-3">
            <div className="mb-2 flex items-center gap-2">
              <p className="text-xs font-medium text-muted-foreground">Dormancy &amp; Reactivation</p>
              <Badge
                variant="outline"
                className={
                  data.dormancy_reactivation.reactivation_detected
                    ? "border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400"
                    : "border-border text-muted-foreground"
                }
              >
                {data.dormancy_reactivation.reactivation_detected
                  ? "Reactivation detected"
                  : "No reactivation detected"}
              </Badge>
            </div>
            {data.dormancy_reactivation.events.length > 0 ? (
              <div className="overflow-hidden rounded-lg ring-1 ring-foreground/10">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Gap Start</TableHead>
                      <TableHead>Gap End</TableHead>
                      <TableHead>Gap (days)</TableHead>
                      <TableHead>Burst Transaction Count</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.dormancy_reactivation.events.map((event, i) => (
                      <TableRow key={`${event.gap_start}-${i}`}>
                        <TableCell className="text-muted-foreground">{formatDateTime(event.gap_start)}</TableCell>
                        <TableCell className="text-muted-foreground">{formatDateTime(event.gap_end)}</TableCell>
                        <TableCell>{event.gap_days}</TableCell>
                        <TableCell>{event.burst_txn_count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">No dormancy-then-reactivation pattern found.</p>
            )}
          </div>

          {data.deferred.length > 0 && (
            <div className="border-t pt-3">
              <p className="mb-1 text-xs font-medium text-muted-foreground">Not Yet Available</p>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
                {data.deferred.map((field) => (
                  <Field key={field} label={deferredLabel(field)} value="Not yet available" />
                ))}
              </dl>
            </div>
          )}
        </div>
      )}
    </TriageSection>
  );
}
