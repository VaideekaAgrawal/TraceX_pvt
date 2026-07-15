"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { InvestigatorWorkloadItem } from "@/lib/api/types";

export interface AssignResult {
  alertId: string;
  success: boolean;
  error?: string;
}

/**
 * Appears when >=1 row is selected, or when a previous bulk-assign's
 * results are still being shown (Admin-only, rendered by
 * `alert-table.tsx`, which owns the `results` state — see that file's
 * render condition). No new bulk-assign endpoint exists at this data
 * scale (matches the backend's scope) — this loops the single `PATCH
 * /api/alerts/{id}/assign` call per selected alert. A loop over N
 * independent HTTP calls can partially fail, so results are shown
 * per-alert rather than a single pass/fail toast.
 *
 * Results deliberately do NOT unmount as a side effect of the post-submit
 * refetch clearing selection (that was the bug: `alert-table.tsx`'s
 * `fetchAlerts` used to unconditionally clear `selected`, which — since
 * this bar only rendered while `selected.size > 0` — wiped the results
 * message before an admin could read it, typically in well under a
 * second). Instead: only successfully-assigned alerts are dropped from
 * selection (via `onAssignComplete`, called with just the succeeded IDs)
 * so failed alerts stay selected for an easy retry, and `results` stays
 * visible until the admin explicitly dismisses it or starts a new submit.
 */
export function BulkAssignBar({
  selectedAlertIds,
  investigators,
  results,
  onResultsChange,
  onAssignComplete,
  onClearSelection,
  onDismissResults,
}: {
  selectedAlertIds: string[];
  investigators: InvestigatorWorkloadItem[];
  results: AssignResult[] | null;
  onResultsChange: (results: AssignResult[] | null) => void;
  onAssignComplete: (succeededAlertIds: string[]) => void;
  onClearSelection: () => void;
  onDismissResults: () => void;
}) {
  const [investigatorId, setInvestigatorId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const hasSelection = selectedAlertIds.length > 0;

  async function handleSubmit() {
    if (!investigatorId || selectedAlertIds.length === 0) return;
    setSubmitting(true);
    onResultsChange(null);

    const outcomes = await Promise.all(
      selectedAlertIds.map(async (alertId): Promise<AssignResult> => {
        try {
          const res = await fetch(`/api/alerts/${encodeURIComponent(alertId)}/assign`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ investigator_id: investigatorId }),
          });
          if (!res.ok) {
            const body = await res.json().catch(() => ({}));
            return {
              alertId,
              success: false,
              error: typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`,
            };
          }
          return { alertId, success: true };
        } catch {
          return { alertId, success: false, error: "Network error" };
        }
      }),
    );

    onResultsChange(outcomes);
    setSubmitting(false);
    onAssignComplete(outcomes.filter((r) => r.success).map((r) => r.alertId));
  }

  const failedCount = results?.filter((r) => !r.success).length ?? 0;
  const succeededCount = results?.filter((r) => r.success).length ?? 0;

  return (
    <div className="bg-secondary/50 flex flex-col gap-2 rounded-xl border p-3">
      {hasSelection && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm font-medium">
            {selectedAlertIds.length} alert{selectedAlertIds.length === 1 ? "" : "s"} selected
          </span>

          <Select
            value={investigatorId ?? undefined}
            onValueChange={(value) => setInvestigatorId(value ? String(value) : null)}
          >
            <SelectTrigger size="sm" className="w-56">
              <SelectValue placeholder="Assign to…" />
            </SelectTrigger>
            <SelectContent>
              {investigators.map((inv) => (
                <SelectItem key={inv.user_id} value={inv.user_id}>
                  {inv.full_name} — {inv.open_case_count} open case
                  {inv.open_case_count === 1 ? "" : "s"}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button size="sm" disabled={!investigatorId || submitting} onClick={() => void handleSubmit()}>
            {submitting
              ? "Assigning…"
              : `Assign ${selectedAlertIds.length} alert${selectedAlertIds.length === 1 ? "" : "s"}`}
          </Button>

          <Button variant="ghost" size="sm" onClick={onClearSelection}>
            Clear selection
          </Button>
        </div>
      )}

      {results && (
        <div className="flex flex-wrap items-start justify-between gap-3 text-sm">
          <div>
            <p className={failedCount > 0 ? "text-destructive" : "text-foreground"}>
              {succeededCount} succeeded, {failedCount} failed.
              {failedCount > 0 &&
                hasSelection &&
                " Failed alerts remain selected — pick an investigator and retry above."}
            </p>
            {failedCount > 0 && (
              <ul className="text-muted-foreground mt-1 list-inside list-disc">
                {results
                  .filter((r) => !r.success)
                  .map((r) => (
                    <li key={r.alertId}>
                      {r.alertId}: {r.error}
                    </li>
                  ))}
              </ul>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={onDismissResults}>
            Dismiss
          </Button>
        </div>
      )}
    </div>
  );
}
