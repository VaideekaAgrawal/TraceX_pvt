"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SEVERITY_ORDER, severityLabel } from "@/components/dashboard/format";

/**
 * Small horizontal bar chart over the active-alert severity mix. Each bar
 * is labeled with its severity name on the axis AND its count at the bar
 * end — never color alone, even though the bars are also tinted red-to-
 * neutral by severity for a quick visual read.
 */
export function SeverityBreakdownChart({
  severityBreakdown,
}: {
  severityBreakdown: Record<string, number>;
}) {
  const data = SEVERITY_ORDER.map((severity) => ({
    severity,
    label: severityLabel(severity),
    count: severityBreakdown[severity] ?? 0,
  }));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Active Alerts by Severity</CardTitle>
      </CardHeader>
      <CardContent className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 8, right: 24, bottom: 0, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" horizontal={false} className="stroke-border" />
            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
            <YAxis
              type="category"
              dataKey="label"
              width={72}
              tick={{ fontSize: 12 }}
              tickLine={false}
              axisLine={false}
            />
            <Bar dataKey="count" radius={[0, 4, 4, 0]}>
              {data.map((entry) => (
                <Cell
                  key={entry.severity}
                  fill={SEVERITY_FILL[entry.severity] ?? "var(--color-chart-3)"}
                />
              ))}
              <LabelList dataKey="count" position="right" className="fill-foreground text-xs" />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

// `<Bar>`'s `<Cell>` children set the per-bar fill positionally — kept as a
// dedicated color-per-severity map (distinct from `format.ts`'s
// `SEVERITY_BADGE_CLASS`, which is a Tailwind className for the badges,
// not a recharts `fill` color) so the chart's palette is easy to audit in
// one place.
const SEVERITY_FILL: Record<string, string> = {
  LOW: "var(--color-chart-2)",
  MEDIUM: "oklch(0.769 0.188 70.08)",
  HIGH: "oklch(0.704 0.191 22.216)",
  CRITICAL: "oklch(0.577 0.245 27.325)",
};
