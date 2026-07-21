"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageField as Field, TriageSection } from "@/components/workspace/triage/triage-section";
import type { TransactionPurposeResponse, TransactionSummaryResponse } from "@/lib/api/types";

const RECENT_TXN_LIMIT = 10;

/**
 * L1 Triage §5 — Transaction Summary, with Transaction Purpose (§5b) as the
 * same card per spec. Optional `start`/`end` date-range filter on the
 * summary half — the purpose half has no date-range param on the backend
 * route, so it's unfiltered (matches `GET .../transaction-purpose`'s real
 * signature; not adding a client-side-only filter that would misrepresent
 * it as a real backend capability).
 */
export function TransactionSummarySection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  // Bare `YYYY-MM-DD` `<input type="date">` values, passed through as
  // literal date-time strings (no `Date`/`toISOString()` round-trip) —
  // matches `alert-query.ts::endOfDayParam`'s exact convention and its
  // docstring's reasoning: going through a `Date` object applies the
  // browser's local-timezone offset before serializing back to UTC, which
  // silently shifts the selected day by that offset. The backend parses
  // these as naive datetimes and compares directly, so passing the literal
  // string is correct, not a shortcut.
  const qs = new URLSearchParams();
  if (start) qs.set("start", start);
  if (end) qs.set("end", `${end}T23:59:59.999`);
  const summaryUrl = `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/transaction-summary${qs.toString() ? `?${qs.toString()}` : ""}`;
  const purposeUrl = `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/transaction-purpose`;

  const summary = useTriageFetch<TransactionSummaryResponse>(summaryUrl);
  const purpose = useTriageFetch<TransactionPurposeResponse>(purposeUrl);

  const recentTxns = purpose.data
    ? [...purpose.data.transactions]
        .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
        .slice(0, RECENT_TXN_LIMIT)
    : [];

  return (
    <TriageSection
      title="Transaction Summary"
      description="Aggregate in/out activity and per-transaction purpose for the primary account."
      loading={summary.loading}
      error={summary.error}
      action={
        <div className="flex items-end gap-2">
          <div className="flex flex-col gap-1">
            <Label className="text-muted-foreground text-xs font-normal">From</Label>
            <Input type="date" aria-label="From date" value={start} onChange={(e) => setStart(e.target.value)} className="h-7 w-36 text-xs" />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-muted-foreground text-xs font-normal">To</Label>
            <Input type="date" aria-label="To date" value={end} onChange={(e) => setEnd(e.target.value)} className="h-7 w-36 text-xs" />
          </div>
        </div>
      }
    >
      {summary.data && (
        <div className="flex flex-col gap-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <Field label="Total In" value={`₹${summary.data.total_in.toLocaleString()}`} />
            <Field label="Total Out" value={`₹${summary.data.total_out.toLocaleString()}`} />
            <Field label="Transactions" value={String(summary.data.txn_count)} />
            <Field label="Counterparties" value={String(summary.data.counterparty_count)} />
          </dl>

          {Object.keys(summary.data.channel_breakdown).length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Channel Breakdown</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(summary.data.channel_breakdown).map(([channel, count]) => (
                  <Badge key={channel} variant="outline">
                    {channel}: {count}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          <div className="border-t pt-3">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Transaction Purpose</p>
            {purpose.loading && <p className="text-muted-foreground text-sm">Loading…</p>}
            {!purpose.loading && purpose.error && (
              <p className="text-destructive text-sm" role="alert">
                {purpose.error}
              </p>
            )}
            {!purpose.loading && !purpose.error && purpose.data && (
              <>
                <div className="mb-2 flex flex-wrap gap-2">
                  {Object.entries(purpose.data.purpose_distribution).map(([p, count]) => (
                    <Badge key={p} variant="outline">
                      {p}: {count}
                    </Badge>
                  ))}
                </div>
                <div className="overflow-hidden rounded-lg ring-1 ring-foreground/10">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>When</TableHead>
                        <TableHead>Direction</TableHead>
                        <TableHead>Counterparty</TableHead>
                        <TableHead>Amount</TableHead>
                        <TableHead>Channel</TableHead>
                        <TableHead>Purpose</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {recentTxns.length === 0 && (
                        <TableRow>
                          <TableCell colSpan={6} className="text-muted-foreground py-6 text-center">
                            No transactions recorded.
                          </TableCell>
                        </TableRow>
                      )}
                      {recentTxns.map((t) => (
                        <TableRow key={t.txn_id}>
                          <TableCell className="text-muted-foreground">{formatDateTime(t.timestamp)}</TableCell>
                          <TableCell>{t.direction === "in" ? "In" : "Out"}</TableCell>
                          <TableCell>{t.counterparty_account_id}</TableCell>
                          <TableCell>₹{t.amount.toLocaleString()}</TableCell>
                          <TableCell className="text-muted-foreground">{t.channel}</TableCell>
                          <TableCell className="text-muted-foreground">{t.purpose ?? "—"}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
                {purpose.data.transactions.length > RECENT_TXN_LIMIT && (
                  <p className="text-muted-foreground mt-1 text-xs">
                    Showing {RECENT_TXN_LIMIT} most recent of {purpose.data.transactions.length} transactions.
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </TriageSection>
  );
}
