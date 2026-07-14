"use client";

import { useCallback, useState } from "react";

import { AlertTable } from "@/components/dashboard/alert-table";
import { AlertsOverTimeChart } from "@/components/dashboard/alerts-over-time-chart";
import { SeverityBreakdownChart } from "@/components/dashboard/severity-breakdown-chart";
import { SummaryCards } from "@/components/dashboard/summary-cards";
import type { AlertListResponse, DashboardSummaryResponse } from "@/lib/api/types";

/**
 * Composes the summary cards, both charts, and the alert table. Owns the
 * shared refresh trigger described in the task brief: a successful assign
 * (single or bulk, from inside `AlertTable`) calls `refreshSummary`, which
 * re-fetches `/api/dashboard/summary` so the cards/charts reflect the new
 * assignment without a full page reload. `AlertTable` re-fetches its own
 * page independently — it doesn't need this trigger, only the summary
 * does.
 */
export function DashboardContent({
  initialSummary,
  initialAlerts,
}: {
  initialSummary: DashboardSummaryResponse;
  initialAlerts: AlertListResponse;
}) {
  const [summary, setSummary] = useState(initialSummary);

  const refreshSummary = useCallback(async () => {
    try {
      const res = await fetch("/api/dashboard/summary", { cache: "no-store" });
      if (!res.ok) return;
      const body = (await res.json()) as DashboardSummaryResponse;
      setSummary(body);
    } catch {
      // Non-fatal — the cards just keep showing the last known-good
      // summary until the next successful refresh.
    }
  }, []);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="font-heading text-xl font-semibold">Dashboard</h1>
        <p className="text-muted-foreground text-sm">
          System-wide alert landscape — identical view for every role; only assignment
          controls differ.
        </p>
      </div>

      <SummaryCards summary={summary} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <AlertsOverTimeChart data={summary.alerts_over_time} windowDays={summary.window_days} />
        </div>
        <SeverityBreakdownChart severityBreakdown={summary.severity_breakdown} />
      </div>

      <AlertTable initialData={initialAlerts} onAssignSuccess={refreshSummary} />
    </div>
  );
}
