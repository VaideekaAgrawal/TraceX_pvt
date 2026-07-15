import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatRiskScore } from "@/components/dashboard/format";
import type { DashboardSummaryResponse } from "@/lib/api/types";

/**
 * Four KPI stat tiles — presentational, props-driven from
 * `GET /dashboard/summary`. Single current values, not a chart: the two
 * charts live in separate components. The Critical value is the only one
 * colored (semantic red, paired with its "Critical Alerts" label, never
 * color alone) — the rest are neutral, since a plain count isn't itself
 * good or bad the way an unusually high critical count is.
 */
export function SummaryCards({ summary }: { summary: DashboardSummaryResponse }) {
  const criticalCount = summary.severity_breakdown.CRITICAL ?? 0;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard label="Active Alerts" value={summary.active_alert_count.toLocaleString()} />
      <StatCard
        label="Critical Alerts"
        value={criticalCount.toLocaleString()}
        valueClassName="text-red-600 dark:text-red-400"
      />
      <StatCard label="Open Cases" value={summary.open_case_count.toLocaleString()} />
      <StatCard label="Avg Risk Score" value={formatRiskScore(summary.avg_risk_score)} />
    </div>
  );
}

function StatCard({
  label,
  value,
  valueClassName,
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <span className={`text-2xl font-semibold ${valueClassName ?? ""}`}>{value}</span>
      </CardContent>
    </Card>
  );
}
