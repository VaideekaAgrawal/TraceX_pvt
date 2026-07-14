"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/components/dashboard/format";
import type { AlertsOverTimePoint } from "@/lib/api/types";

/**
 * Discrete daily alert counts — a bar chart, not a line, because each day
 * is an independent count rather than a continuous trend. Single series
 * (no legend needed — the card title already names it), hover tooltip on
 * every bar.
 *
 * On the real dataset this will show one real spike day and zero-filled
 * bars for the rest of the window (`investigation/dashboard.py`'s
 * docstring: every alert currently comes from one historical pipeline
 * run) — expected, not a bug to paper over with a smoothed series.
 */
export function AlertsOverTimeChart({
  data,
  windowDays,
}: {
  data: AlertsOverTimePoint[];
  windowDays: number;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Alerts Over Time</CardTitle>
        <p className="text-muted-foreground text-xs">Last {windowDays} days</p>
      </CardHeader>
      <CardContent className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" vertical={false} className="stroke-border" />
            <XAxis
              dataKey="date"
              tickFormatter={formatDate}
              tick={{ fontSize: 11 }}
              interval="preserveStartEnd"
            />
            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={32} />
            <Tooltip
              labelFormatter={(label) => formatDate(String(label))}
              formatter={(value) => [String(value), "Alerts"]}
              contentStyle={{
                fontSize: 12,
                borderRadius: 8,
                border: "1px solid var(--border)",
              }}
            />
            <Bar dataKey="count" fill="var(--color-chart-1)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
