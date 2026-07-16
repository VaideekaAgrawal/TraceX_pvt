"use client";

import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detectionTypeLabel, formatDateTime, formatRiskScore, severityBadgeClassName } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { AlertSummaryItem } from "@/lib/api/types";

/**
 * L1 Triage §1 — Alert Summary. `GET /cases/{case_id}/summary/alerts`, all
 * alerts on this case (not just the primary one).
 */
export function AlertSummarySection({ caseId }: { caseId: string }) {
  const { data, loading, error } = useTriageFetch<AlertSummaryItem[]>(
    `/api/cases/${encodeURIComponent(caseId)}/summary/alerts`,
  );

  return (
    <TriageSection
      title="Alert Summary"
      loading={loading}
      error={error}
      isEmpty={!!data && data.length === 0}
      emptyText="No alerts recorded on this case."
    >
      <div className="overflow-hidden rounded-lg ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Alert</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Severity</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>Risk Score</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last Seen</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data ?? []).map((alert) => (
              <TableRow key={alert.alert_id}>
                <TableCell className="font-medium">{alert.alert_id}</TableCell>
                <TableCell>{detectionTypeLabel(alert.detection_type)}</TableCell>
                <TableCell>
                  <Badge variant="outline" className={severityBadgeClassName(alert.severity)}>
                    {alert.severity}
                  </Badge>
                </TableCell>
                <TableCell>{alert.priority}</TableCell>
                <TableCell>{formatRiskScore(alert.risk_score)}</TableCell>
                <TableCell className="text-muted-foreground">{alert.status}</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(alert.last_seen_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </TriageSection>
  );
}
