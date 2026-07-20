"use client";

import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useAuth, useRole } from "@/lib/auth/auth-provider";
import { isAssignedToUser } from "@/lib/workspace/case-assignment";
import { getCaseStageLabel, getDefaultActiveView } from "@/lib/workspace/case-stage";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import type { DecisionRequest, DecisionResponse, DecisionValue } from "@/lib/api/types";

const CLOSED_STATUSES = new Set(["CLOSED_FP", "CLOSED_TP"]);

type SubmitKey =
  | "escalate"
  | "recommend_fp"
  | "recommend_monitoring"
  | "close_fp"
  | "close_monitoring";

/**
 * L1/L2 Decision Panel — role- AND status-aware, mounted once in
 * `case-tab-content.tsx`'s always-visible zone (not inside `triage-view.tsx`)
 * so it's reachable from both Triage and Deep Investigation.
 *
 * Every button offered here must be legal per `investigation.fsm.
 * VALID_TRANSITIONS` for the case's CURRENT status, not just the current
 * role — offering an action the FSM would 409 on is the same bug class as
 * the `ASSIGNED -> ESCALATED` gap fixed earlier (see `case-tab-content.
 * tsx`'s auto-start effect). Per `make_decision`'s docstring
 * (`backend/api/routes/cases.py`), the FSM-legal status range for each
 * decision value is:
 *
 *   - `escalate` -> `ESCALATED`, legal only from `IN_PROGRESS`, open to any
 *     investigator with case access (or Admin/Compliance).
 *   - `request_info` -> `AWAITING_REVIEW`, legal only from `IN_PROGRESS`.
 *     Not offered as its own literal button — the old "Request More Info"
 *     UI framing was removed entirely. It now only fires under two
 *     Investigator-only UI-framing buttons ("Recommend False Positive" /
 *     "Recommend Monitoring") that submit this same decision value with a
 *     distinguishing reason prefix, routing the case into Admin/
 *     Compliance's `AWAITING_REVIEW` queue for a real decision — an
 *     Investigator can never trigger real `close_fp`/`close_monitoring`
 *     directly, same reasoning for both.
 *   - `close_fp` -> `CLOSED_FP`. FSM-legal from `IN_PROGRESS`/
 *     `AWAITING_REVIEW`/`ESCALATED`, but Admin/Compliance-only — a separate
 *     RBAC layer on top of the FSM range.
 *   - `close_monitoring` -> `MONITORING` (`ENHANCED_MONITORING` resolution).
 *     FSM-legal only from `AWAITING_REVIEW`/`ESCALATED` — NOT directly from
 *     `IN_PROGRESS` — and Admin/Compliance-only, same RBAC gate as
 *     `close_fp`.
 *
 * Rendering rules, derived from the above:
 *   - Investigator: "Escalate" / "Recommend False Positive" / "Recommend
 *     Monitoring" shown together only when `status === "IN_PROGRESS"`
 *     (the only status any of their underlying calls are FSM-legal from).
 *     When the case is open but in some other status the investigator
 *     can't act from (`AWAITING_REVIEW`, `ESCALATED`), an informational
 *     message is shown instead of empty/illegal buttons — the case is
 *     legitimately just waiting on someone else right now.
 *   - Admin/Compliance: real "Escalate" (`status === "IN_PROGRESS"`, same
 *     as an investigator), real "Monitoring" (`status === "AWAITING_REVIEW"
 *     || "ESCALATED"` — the FSM-legal window, never offered outside it),
 *     real "Close — False Positive" (`status` any of the three FSM-legal
 *     statuses `close_fp` documents). Falls back to the same informational
 *     message if none currently apply (shouldn't happen given those ranges
 *     cover every open status, but handled defensively).
 *
 * RBAC is enforced server-side; which buttons render here is a UX courtesy
 * only — a role/FSM disagreement always surfaces the backend's real
 * 403/409, never a swallowed generic error.
 *
 * Assignment-aware gating: every WRITE route this panel calls (`/decision`)
 * stays assignment-gated server-side even though every GET route is open to
 * any authenticated user (see `case-detail-client.ts`'s `getCase`
 * docstring) — an Investigator who opened this case read-only via Similar
 * Cases/Previous History (not assigned to them) would otherwise hit a real
 * 403 the moment they tried to act. Rather than let that happen, an
 * Investigator viewing a case not assigned to them sees a short read-only
 * message instead of any action controls. Admin/Compliance keeps full
 * access regardless of `assigned_to` (matches the backend's own
 * `require_case_access` bypass for that role).
 *
 * No note field here — the single Notes entry point is `NotesPanel`
 * (mounted alongside this panel in `case-tab-content.tsx`'s always-visible
 * zone), not a second compose box duplicated into every decision submit.
 */
export function DecisionPanel({ caseId }: { caseId: string }) {
  const role = useRole();
  const isAdmin = role === "ADMIN_COMPLIANCE";
  const { user } = useAuth();

  const summary = useCaseTabStore((state) => state.tabState[caseId]?.summary);
  const status = summary?.status ?? "";
  const isReadOnly = !isAdmin && summary != null && !isAssignedToUser(summary, user?.user_id);
  const updateTabState = useCaseTabStore((state) => state.updateTabState);

  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState<SubmitKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const isClosed = CLOSED_STATUSES.has(status);

  async function submit(
    decision: DecisionValue,
    reasonText: string,
    successMessage: string,
    key: SubmitKey,
  ) {
    setSubmitting(key);
    setError(null);
    setSuccess(null);
    try {
      const body: DecisionRequest = { decision, reason: reasonText };

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
      // badge (and this panel's own button set) reflects the new status
      // without a manual refresh — same principle as Phase 15's `openCase`
      // fix that always refreshes `summary` (see `case-tab-store.ts`). Also
      // recomputes the default `activeView` for this same status transition
      // (ROADMAP Phase 17) — e.g. escalating a case here flips the
      // investigator straight into Deep Investigation.
      const currentSummary = useCaseTabStore.getState().tabState[caseId]?.summary;
      if (currentSummary) {
        updateTabState(caseId, {
          summary: { ...currentSummary, status: result.status },
          activeView: getDefaultActiveView(result.status),
        });
      }

      setSuccess(successMessage);
      setReason("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit decision");
    } finally {
      setSubmitting(null);
    }
  }

  function handleSubmit(kind: SubmitKey) {
    const trimmedReason = reason.trim();
    if (!trimmedReason) {
      setError("A reason is required.");
      setSuccess(null);
      return;
    }
    if (kind === "escalate") {
      void submit("escalate", trimmedReason, "Case escalated to Deep Investigation.", "escalate");
    } else if (kind === "recommend_fp") {
      // UI framing only — still `request_info` under the hood, never
      // `close_fp`, per this panel's docstring.
      void submit(
        "request_info",
        `[Recommended False Positive] ${trimmedReason}`,
        "Recommended as False Positive — routed to Admin/Compliance for closure.",
        "recommend_fp",
      );
    } else if (kind === "recommend_monitoring") {
      // Same UI-framing pattern as `recommend_fp` — still `request_info`
      // under the hood, never real `close_monitoring`, per this panel's
      // docstring.
      void submit(
        "request_info",
        `[Recommended Monitoring] ${trimmedReason}`,
        "Recommended Monitoring — routed to Admin/Compliance for review.",
        "recommend_monitoring",
      );
    } else if (kind === "close_monitoring") {
      void submit(
        "close_monitoring",
        trimmedReason,
        "Case set to Enhanced Monitoring.",
        "close_monitoring",
      );
    } else {
      void submit("close_fp", trimmedReason, "Case closed as False Positive.", "close_fp");
    }
  }

  const canAct = !isClosed && !isReadOnly;
  const investigatorCanAct = canAct && !isAdmin && status === "IN_PROGRESS";
  const adminShowEscalate = canAct && isAdmin && status === "IN_PROGRESS";
  const adminShowMonitoring =
    canAct && isAdmin && (status === "AWAITING_REVIEW" || status === "ESCALATED");
  const adminShowCloseFp =
    canAct &&
    isAdmin &&
    (status === "IN_PROGRESS" || status === "AWAITING_REVIEW" || status === "ESCALATED");
  const adminHasAnyAction = adminShowEscalate || adminShowMonitoring || adminShowCloseFp;
  const noActionAvailable = canAct && (isAdmin ? !adminHasAnyAction : !investigatorCanAct);

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
        ) : isReadOnly ? (
          <p className="text-muted-foreground text-sm">
            This case isn&apos;t assigned to you — you&apos;re viewing it read-only.
          </p>
        ) : noActionAvailable ? (
          <p className="text-muted-foreground text-sm">
            This case is awaiting compliance review — no action needed from you right now.
          </p>
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
              {investigatorCanAct && (
                <>
                  <Button
                    variant="outline"
                    onClick={() => handleSubmit("escalate")}
                    disabled={submitting !== null}
                  >
                    {submitting === "escalate" ? "Escalating…" : "Escalate to Deep Investigation"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => handleSubmit("recommend_fp")}
                    disabled={submitting !== null}
                  >
                    {submitting === "recommend_fp" ? "Submitting…" : "Recommend False Positive"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => handleSubmit("recommend_monitoring")}
                    disabled={submitting !== null}
                  >
                    {submitting === "recommend_monitoring" ? "Submitting…" : "Recommend Monitoring"}
                  </Button>
                </>
              )}
              {adminShowEscalate && (
                <Button
                  variant="outline"
                  onClick={() => handleSubmit("escalate")}
                  disabled={submitting !== null}
                >
                  {submitting === "escalate" ? "Escalating…" : "Escalate to Deep Investigation"}
                </Button>
              )}
              {adminShowMonitoring && (
                <Button
                  variant="outline"
                  onClick={() => handleSubmit("close_monitoring")}
                  disabled={submitting !== null}
                >
                  {submitting === "close_monitoring" ? "Submitting…" : "Monitoring"}
                </Button>
              )}
              {adminShowCloseFp && (
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
