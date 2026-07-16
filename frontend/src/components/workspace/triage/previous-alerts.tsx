"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime, formatRiskScore } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageField as Field, TriageSection } from "@/components/workspace/triage/triage-section";
import type { PreviousAlertsResponse } from "@/lib/api/types";

/**
 * L1 Triage §6 — Previous Investigation History. Scoped to the primary
 * account only, excluding the current case, per `GET .../previous-alerts`.
 */
export function PreviousAlertsSection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const { data, loading, error } = useTriageFetch<PreviousAlertsResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/previous-alerts`,
  );

  return (
    <TriageSection
      title="Previous Investigation History"
      description="Prior alerts on this account, excluding the current case."
      loading={loading}
      error={error}
      isEmpty={!!data && data.total_prior_alerts === 0}
      emptyText="No prior alerts recorded for this account."
    >
      {data && (
        <div className="flex flex-col gap-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <Field label="Total Prior Alerts" value={String(data.total_prior_alerts)} />
            <Field label="Prior SARs" value={String(data.prior_sar_count)} />
            <Field label="Prior False Positives" value={String(data.prior_false_positive_count)} />
            <Field label="Prior Monitoring" value={String(data.prior_monitoring_count)} />
          </dl>

          {data.risk_trend.length > 0 && (
            <div className="overflow-hidden rounded-lg ring-1 ring-foreground/10">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Alert</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Risk Score</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.risk_trend.map((p) => (
                    <TableRow key={p.alert_id}>
                      <TableCell className="font-medium">{p.alert_id}</TableCell>
                      <TableCell className="text-muted-foreground">{formatDateTime(p.created_at)}</TableCell>
                      <TableCell>{formatRiskScore(p.risk_score)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
    </TriageSection>
  );
}
