"use client";

import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useRole } from "@/lib/auth/auth-provider";
import { getCaseStageLabel } from "@/lib/workspace/case-stage";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import type { DecisionRequest, DecisionResponse, DecisionValue } from "@/lib/api/types";

const CLOSED_STATUSES = new Set(["CLOSED_FP", "CLOSED_TP"]);

/**
 * L1 Triage Decision Panel — role-aware exactly per `FRONTEND_PLAN.md`
 * §3.3's correction table:
 *
 *   - Investigator: Escalate / Request More Info (both call `/decision`
 *     directly) + "Recommend False Positive" — UI framing only, submits
 *     `decision: "request_info"` with a distinguishing reason prefix, NEVER
 *     `close_fp` (the backend hard-403s that for a non-Admin — this button
 *     must not even attempt it, so an Investigator never sees a real 403 in
 *     the browser).
 *   - Admin/Compliance: the same Escalate / Request-Info controls, plus a
 *     real "Close — False Positive" (`close_fp`) that actually closes.
 *
 * RBAC is enforced server-side; which buttons render here is a UX courtesy
 * only (`FRONTEND_ROADMAP.md` decision 6) — a role/FSM disagreement always
 * surfaces the backend's real 403/409, never a swallowed generic error.
 */
export function DecisionPanel({ caseId }: { caseId: string }) {
  const role = useRole();
  const isAdmin = role === "ADMIN_COMPLIANCE";

  const status = useCaseTabStore((state) => state.tabState[caseId]?.summary.status ?? "");
  const updateTabState = useCaseTabStore((state) => state.updateTabState);

  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState<DecisionValue | "recommend_fp" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isClosed = CLOSED_STATUSES.has(status);

  async function submit(decision: DecisionValue, reasonText: string, successMessage: string, key: DecisionValue | "recommend_fp") {
    setSubmitting(key);
    setError(null);
    setSuccess(null);
    try {
      const body: DecisionRequest = { decision, reason: reasonText };
      if (note.trim()) body.note = note.trim();

      const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const responseBody = await res.json();
      if (!res.ok) {
        throw new Error(
          typeof responseBody.detail === "string" ? responseBody.detail : "Failed to submit decision",
        );
      }
      const result = responseBody as DecisionResponse;

      // Update the tab's cached summary status immediately so the stage
      // badge reflects the new status without a manual refresh — same
      // principle as Phase 15's `openCase` fix that always refreshes
      // `summary` (see `case-tab-store.ts`).
      const currentSummary = useCaseTabStore.getState().tabState[caseId]?.summary;
      if (currentSummary) {
        updateTabState(caseId, { summary: { ...currentSummary, status: result.status } });
      }

      setSuccess(successMessage);
      setReason("");
      setNote("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit decision");
    } finally {
      setSubmitting(null);
    }
  }

  function handleSubmit(kind: "escalate" | "request_info" | "recommend_fp" | "close_fp") {
    const trimmedReason = reason.trim();
    if (!trimmedReason) {
      setError("A reason is required.");
      setSuccess(null);
      return;
    }
    if (kind === "escalate") {
      void submit("escalate", trimmedReason, "Case escalated to Deep Investigation.", "escalate");
    } else if (kind === "request_info") {
      void submit("request_info", trimmedReason, "Case moved to Awaiting Review.", "request_info");
    } else if (kind === "recommend_fp") {
      // UI framing only — still `request_info` under the hood, never
      // `close_fp`, per this panel's docstring.
      void submit(
        "request_info",
        `[Recommended False Positive] ${trimmedReason}`,
        "Recommended as False Positive — routed to Admin/Compliance for closure.",
        "recommend_fp",
      );
    } else {
      void submit("close_fp", trimmedReason, "Case closed as False Positive.", "close_fp");
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Decision</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-muted-foreground text-sm">
          Current stage: <span className="font-medium text-foreground">{getCaseStageLabel(status)}</span>
        </p>

        {isClosed ? (
          <p className="text-muted-foreground text-sm">This case is closed — no further decision needed.</p>
        ) : (
          <>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`decision-reason-${caseId}`}>Reason (required)</Label>
              <textarea
                id={`decision-reason-${caseId}`}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Why are you making this decision?"
                className="border-input min-h-16 rounded-lg border bg-transparent p-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`decision-note-${caseId}`}>Additional note (optional)</Label>
              <textarea
                id={`decision-note-${caseId}`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Recorded as a case note alongside this decision."
                className="border-input min-h-12 rounded-lg border bg-transparent p-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              />
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertTitle>Decision failed</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {success && (
              <Alert>
                <AlertTitle>Done</AlertTitle>
                <AlertDescription>{success}</AlertDescription>
              </Alert>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                onClick={() => handleSubmit("escalate")}
                disabled={submitting !== null}
              >
                {submitting === "escalate" ? "Escalating…" : "Escalate to Deep Investigation"}
              </Button>
              <Button
                variant="outline"
                onClick={() => handleSubmit("request_info")}
                disabled={submitting !== null}
              >
                {submitting === "request_info" ? "Submitting…" : "Request More Info"}
              </Button>
              {!isAdmin && (
                <Button
                  variant="outline"
                  onClick={() => handleSubmit("recommend_fp")}
                  disabled={submitting !== null}
                >
                  {submitting === "recommend_fp" ? "Submitting…" : "Recommend False Positive"}
                </Button>
              )}
              {isAdmin && (
                <Button
                  variant="destructive"
                  onClick={() => handleSubmit("close_fp")}
                  disabled={submitting !== null}
                >
                  {submitting === "close_fp" ? "Closing…" : "Close — False Positive"}
                </Button>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
