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

interface AssignResult {
  alertId: string;
  success: boolean;
  error?: string;
}

/**
 * Appears when >=1 row is selected (Admin-only, rendered by
 * `alert-table.tsx`). No new bulk-assign endpoint exists at this data
 * scale (matches the backend's scope) — this loops the single `PATCH
 * /api/alerts/{id}/assign` call per selected alert. A loop over N
 * independent HTTP calls can partially fail, so results are shown
 * per-alert rather than a single pass/fail toast.
 */
export function BulkAssignBar({
  selectedAlertIds,
  investigators,
  onDone,
  onClearSelection,
}: {
  selectedAlertIds: string[];
  investigators: InvestigatorWorkloadItem[];
  onDone: () => void;
  onClearSelection: () => void;
}) {
  const [investigatorId, setInvestigatorId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [results, setResults] = useState<AssignResult[] | null>(null);

  async function handleSubmit() {
    if (!investigatorId) return;
    setSubmitting(true);
    setResults(null);

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

    setResults(outcomes);
    setSubmitting(false);
    onDone();
  }

  const failedCount = results?.filter((r) => !r.success).length ?? 0;
  const succeededCount = results?.filter((r) => r.success).length ?? 0;

  return (
    <div className="bg-secondary/50 flex flex-col gap-2 rounded-xl border p-3">
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

      {results && (
        <div className="text-sm">
          <p className={failedCount > 0 ? "text-destructive" : "text-foreground"}>
            {succeededCount} succeeded, {failedCount} failed.
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
      )}
    </div>
  );
}
