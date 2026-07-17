"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime, formatRiskScore } from "@/components/dashboard/format";
import { cn } from "@/lib/utils";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageField as Field, TriageSection } from "@/components/workspace/triage/triage-section";
import type { CaseListItem, PreviousAlertsResponse } from "@/lib/api/types";

// Server-side cap on `risk_trend` is 100 entries (`investigation/
// previous_alerts.py`) — paginated client-side over the already-fetched
// array, no new backend query params.
const PAGE_SIZE = 10;

/**
 * L1 Triage §6 — Previous Investigation History. Scoped to the primary
 * account only, excluding the current case, per `GET .../previous-alerts`.
 * Rows with a non-null `case_id` are clickable — opens that prior case as a
 * real tab, same `GET /api/cases/{case_id}` + `openCase` convergence point
 * `similar-cases.tsx` uses. Rows with `case_id: null` (a prior alert that
 * never became a case — documented, expected, nullable per that endpoint)
 * are not clickable and show no error state.
 */
export function PreviousAlertsSection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const { data, loading, error } = useTriageFetch<PreviousAlertsResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/previous-alerts`,
  );

  const openCase = useCaseTabStore((state) => state.openCase);
  const [page, setPage] = useState(0);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const rows = data?.risk_trend ?? [];
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const clampedPage = Math.min(page, pageCount - 1);
  const pageRows = rows.slice(clampedPage * PAGE_SIZE, clampedPage * PAGE_SIZE + PAGE_SIZE);

  async function handleOpen(targetCaseId: string) {
    setOpenError(null);
    setOpeningId(targetCaseId);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(targetCaseId)}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to open case");
      }
      openCase(body as CaseListItem);
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : "Failed to open case");
    } finally {
      setOpeningId(null);
    }
  }

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

          {rows.length > 0 && (
            <div className="flex flex-col gap-2">
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
                    {pageRows.map((p) => {
                      const clickable = p.case_id != null;
                      return (
                        <TableRow
                          key={p.alert_id}
                          onClick={clickable ? () => void handleOpen(p.case_id as string) : undefined}
                          role={clickable ? "button" : undefined}
                          tabIndex={clickable ? 0 : undefined}
                          onKeyDown={
                            clickable
                              ? (e) => {
                                  if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault();
                                    void handleOpen(p.case_id as string);
                                  }
                                }
                              : undefined
                          }
                          className={cn(
                            clickable && "cursor-pointer",
                            clickable && openingId === p.case_id && "opacity-60",
                          )}
                        >
                          <TableCell className="font-medium">{p.alert_id}</TableCell>
                          <TableCell className="text-muted-foreground">{formatDateTime(p.created_at)}</TableCell>
                          <TableCell>{formatRiskScore(p.risk_score)}</TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>

              {openError && (
                <p className="text-destructive text-xs" role="alert">
                  {openError}
                </p>
              )}

              {pageCount > 1 && (
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    Page {clampedPage + 1} of {pageCount} ({rows.length} prior alerts)
                  </span>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={clampedPage === 0}
                      onClick={() => setPage((p) => Math.max(0, p - 1))}
                    >
                      Prev
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={clampedPage >= pageCount - 1}
                      onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </TriageSection>
  );
}
