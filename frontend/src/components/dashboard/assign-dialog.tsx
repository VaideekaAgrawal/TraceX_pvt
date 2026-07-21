"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AssignAlertResponse, InvestigatorWorkloadItem } from "@/lib/api/types";

/**
 * Admin/Compliance-only manual (re)assignment. Reuses the same `GET
 * /alerts/workload` data the filter bar already loaded (passed down as
 * `investigators`) rather than issuing a second "list investigators"
 * fetch.
 */
export function AssignDialog({
  alertId,
  currentAssignedToName,
  investigators,
  onAssigned,
}: {
  alertId: string;
  currentAssignedToName: string | null;
  investigators: InvestigatorWorkloadItem[];
  onAssigned: (result: AssignAlertResponse) => void;
}) {
  const [open, setOpen] = useState(false);
  const [investigatorId, setInvestigatorId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!investigatorId) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch(`/api/alerts/${encodeURIComponent(alertId)}/assign`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ investigator_id: investigatorId }),
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to assign alert");
      }
      onAssigned(body as AssignAlertResponse);
      setOpen(false);
      setInvestigatorId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to assign alert");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setError(null);
          setInvestigatorId(null);
        }
      }}
    >
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        {currentAssignedToName ? "Reassign" : "Assign"}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{currentAssignedToName ? "Reassign alert" : "Assign alert"}</DialogTitle>
          <DialogDescription>
            {currentAssignedToName
              ? `Currently assigned to ${currentAssignedToName}. Choose a new investigator.`
              : "Choose an investigator to assign this alert's case to."}
          </DialogDescription>
        </DialogHeader>

        <Select value={investigatorId ?? undefined} onValueChange={(value) => setInvestigatorId(value ? String(value) : null)}>
          <SelectTrigger className="w-full" aria-label="Investigator">
            <SelectValue placeholder="Select an investigator" />
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

        {error && (
          <p className="text-destructive text-sm" role="alert">
            {error}
          </p>
        )}

        <DialogFooter>
          <Button
            onClick={() => void handleSubmit()}
            disabled={!investigatorId || submitting}
          >
            {submitting ? "Assigning…" : "Confirm"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
