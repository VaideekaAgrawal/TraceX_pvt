"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime } from "@/components/dashboard/format";
import { getCaseStageLabel } from "@/lib/workspace/case-stage";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import { useRole } from "@/lib/auth/auth-provider";
import type { CaseListItem, CaseListResponse } from "@/lib/api/types";

// Mirrors `alert-filters.tsx`'s `PRIORITY_OPTIONS` — kept local rather than
// imported to avoid coupling the Workspace to the Dashboard feature's own
// filter-bar module for a 4-item constant.
const PRIORITY_OPTIONS = ["P1", "P2", "P3", "P4"];

// `db/enums.py::CaseStatus`, full set — offered to an Investigator (their
// `assigned_to = me` queue accepts any status as a narrowing filter). An
// Admin/Compliance queue is scoped to `AWAITING_REVIEW`/`ESCALATED` only
// (`_ADMIN_QUEUE_STATUSES` in `api/routes/cases.py`) — any other value the
// backend rejects with 400, so the Admin dropdown below only offers the
// legal subset rather than letting them pick a filter guaranteed to error.
const INVESTIGATOR_STATUS_OPTIONS = [
  "NEW",
  "ASSIGNED",
  "IN_PROGRESS",
  "AWAITING_REVIEW",
  "ESCALATED",
  "MONITORING",
  "CLOSED_FP",
  "CLOSED_TP",
];
const ADMIN_STATUS_OPTIONS = ["AWAITING_REVIEW", "ESCALATED"];

// Sentinel for "no filter" in the base-ui `Select` (needs a real string
// value for the "All" item, not `undefined`/`null`) — same convention as
// `alert-filters.tsx`.
const ALL = "__all__";

// Matches `_CaseListParams.limit`'s own default server-side — this phase's
// queues are naturally small (an investigator's own assigned cases, or the
// system-wide Admin/Compliance review queue), so no pagination UI is built
// here; a queue that exceeds this in practice is a gap worth flagging for a
// later phase, not something to silently truncate without a UI cue.
const QUEUE_LIMIT = 200;

export function CaseQueue({ initialData }: { initialData: CaseListResponse }) {
  const role = useRole();
  const isAdmin = role === "ADMIN_COMPLIANCE";
  const statusOptions = isAdmin ? ADMIN_STATUS_OPTIONS : INVESTIGATOR_STATUS_OPTIONS;

  const openCase = useCaseTabStore((state) => state.openCase);

  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [data, setData] = useState<CaseListResponse>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const skipNextFetch = useRef(true);
  // Guards against a stale response overwriting a newer one when the user
  // toggles filters faster than a request round-trips (no AbortController
  // needed — we just ignore any response that isn't from the most recent
  // call).
  const latestRequestId = useRef(0);

  const fetchCases = useCallback(async () => {
    const requestId = ++latestRequestId.current;
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = { limit: String(QUEUE_LIMIT), offset: "0" };
      if (status) params.status = status;
      if (priority) params.priority = priority;
      const qs = new URLSearchParams(params).toString();
      const res = await fetch(`/api/cases?${qs}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to load cases");
      }
      if (requestId === latestRequestId.current) {
        setData(body as CaseListResponse);
      }
    } catch (err) {
      if (requestId === latestRequestId.current) {
        setError(err instanceof Error ? err.message : "Failed to load cases");
      }
    } finally {
      if (requestId === latestRequestId.current) {
        setLoading(false);
      }
    }
  }, [status, priority]);

  useEffect(() => {
    if (skipNextFetch.current) {
      skipNextFetch.current = false;
      return;
    }
    void fetchCases();
  }, [fetchCases]);

  const emptyStateText = isAdmin ? "No cases awaiting review." : "No cases assigned to you.";

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3 rounded-xl border p-3">
        <Field label="Status">
          <Select
            value={status || ALL}
            onValueChange={(value) => setStatus(value === ALL ? "" : String(value))}
          >
            <SelectTrigger size="sm" className="w-40" aria-label="Status">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All statuses</SelectItem>
              {statusOptions.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field label="Priority">
          <Select
            value={priority || ALL}
            onValueChange={(value) => setPriority(value === ALL ? "" : String(value))}
          >
            <SelectTrigger size="sm" className="w-28" aria-label="Priority">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All priorities</SelectItem>
              {PRIORITY_OPTIONS.map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>

      {error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}

      <div className="overflow-hidden rounded-xl ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Case ID</TableHead>
              <TableHead>Primary Account</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground py-8 text-center">
                  {emptyStateText}
                </TableCell>
              </TableRow>
            )}
            {data.items.map((item) => (
              <CaseRow key={item.case_id} item={item} onOpen={() => openCase(item)} />
            ))}
          </TableBody>
        </Table>
      </div>

      <p className="text-muted-foreground text-sm">
        {data.total_count === 0
          ? "No cases"
          : `Showing ${data.items.length} of ${data.total_count.toLocaleString()}`}
      </p>
    </div>
  );
}

function CaseRow({ item, onOpen }: { item: CaseListItem; onOpen: () => void }) {
  return (
    <TableRow
      onClick={onOpen}
      className="cursor-pointer"
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
    >
      <TableCell className="font-medium">{item.case_id}</TableCell>
      <TableCell>{item.primary_account_id}</TableCell>
      <TableCell>
        <Badge variant="outline">{getCaseStageLabel(item.status)}</Badge>
      </TableCell>
      <TableCell>
        <Badge variant="outline">{item.priority}</Badge>
      </TableCell>
      <TableCell className="text-muted-foreground">{item.status}</TableCell>
      <TableCell className="text-muted-foreground">{formatDateTime(item.updated_at)}</TableCell>
    </TableRow>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-muted-foreground text-xs font-normal">{label}</Label>
      {children}
    </div>
  );
}
