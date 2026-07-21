"use client";

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime } from "@/components/dashboard/format";
import { cn } from "@/lib/utils";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { TimelineResponse } from "@/lib/api/types";

/**
 * L2 §3 — Investigation Timeline, wired to `GET .../timeline` (ROADMAP
 * Phase 17). Clicking a row correlates with `investigation-graph.tsx` by
 * shared `txn_id` — pure client-side match, the designed data contract
 * (`investigation/timeline.py`'s docstring), no extra backend call. A row
 * whose `txn_id` isn't present in the graph's *current* filtered view (e.g.
 * filtered out by a graph-only filter) still selects/highlights here; the
 * graph simply won't have a matching edge to highlight in that case — an
 * expected outcome of two independently filterable views sharing one key,
 * not a bug.
 */
export function InvestigationTimelineSection({
  caseId,
  accountId,
  selectedTxnId,
  onSelectTxn,
}: {
  caseId: string;
  accountId: string;
  selectedTxnId: string | null;
  onSelectTxn: (txnId: string | null) => void;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const url = useMemo(() => {
    const qs = new URLSearchParams();
    if (start) qs.set("start", start);
    // `end` is a bare `YYYY-MM-DD` string from a `type="date"` input; the
    // backend parses it as an exact `datetime` compared with `<=`, so
    // passing it through as-is lands on that date's midnight and silently
    // excludes almost the entire selected end day — same fix as
    // `alert-query.ts::endOfDayParam` / `transaction-summary.tsx`'s
    // identical local convention, applied here too.
    if (end) qs.set("end", `${end}T23:59:59.999`);
    const query = qs.toString();
    return `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/timeline${query ? `?${query}` : ""}`;
  }, [caseId, accountId, start, end]);

  const { data, loading, error } = useTriageFetch<TimelineResponse>(url);

  return (
    <TriageSection
      title="Investigation Timeline"
      description="Chronological reconstruction of every transaction touching this account. Click a row to highlight its edge in the graph above."
      loading={loading}
      error={error}
      isEmpty={!!data && data.events.length === 0}
      emptyText="No transactions recorded for this account in the selected window."
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex flex-col gap-1">
            <Label className="text-muted-foreground text-xs font-normal">From</Label>
            <Input type="date" aria-label="From date" className="w-36" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-muted-foreground text-xs font-normal">To</Label>
            <Input type="date" aria-label="To date" className="w-36" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
        </div>

        {data && data.events.length > 0 && (
          <div
            tabIndex={0}
            role="region"
            aria-label="Timeline events, scrollable"
            className="max-h-96 overflow-y-auto overflow-x-hidden rounded-lg ring-1 ring-foreground/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Timestamp</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Counterparty</TableHead>
                  <TableHead>Amount</TableHead>
                  <TableHead>Channel</TableHead>
                  <TableHead>Flag</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.events.map((event) => (
                  <TableRow
                    key={event.txn_id}
                    onClick={() => onSelectTxn(event.txn_id === selectedTxnId ? null : event.txn_id)}
                    className={cn(
                      "cursor-pointer",
                      event.txn_id === selectedTxnId && "bg-accent",
                    )}
                  >
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(event.timestamp)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{event.direction === "in" ? "Inbound" : "Outbound"}</Badge>
                    </TableCell>
                    <TableCell className="font-medium">{event.counterparty_account_id}</TableCell>
                    <TableCell>₹{event.amount.toLocaleString()}</TableCell>
                    <TableCell className="text-muted-foreground">{event.channel}</TableCell>
                    <TableCell>
                      {event.is_laundering && (
                        <Badge
                          variant="outline"
                          className="border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400"
                        >
                          Flagged
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </TriageSection>
  );
}
