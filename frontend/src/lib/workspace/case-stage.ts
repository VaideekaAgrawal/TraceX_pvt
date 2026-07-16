/**
 * Single source of truth for "backend `CaseStatus` -> investigator-facing
 * stage badge" (`docs/FRONTEND_PLAN.md` §3.2, ROADMAP Phase 15). Display-only
 * — no new backend state. Imported by both the queue list
 * (`case-queue.tsx`) and the tab bar/tab body (`case-tab-bar.tsx`,
 * `case-tab-content.tsx`); never reimplemented in either.
 *
 * `status` is typed as a plain `string` here (not a re-declared union),
 * matching this codebase's existing convention for backend controlled
 * vocabularies (see `lib/api/types.ts`'s `AlertListItem.status`) — the
 * backend's `db.enums.CaseStatus` is the actual source of truth, this is
 * just a display mapping over its serialized string values.
 */

export const CASE_STAGE_LABELS: Record<string, string> = {
  NEW: "Triage",
  ASSIGNED: "Triage",
  IN_PROGRESS: "Triage",
  AWAITING_REVIEW: "Awaiting Review",
  ESCALATED: "Deep Investigation",
  MONITORING: "Monitoring",
  CLOSED_FP: "Closed — False Positive",
  CLOSED_TP: "Closed — Confirmed",
};

/**
 * Falls back to "Unknown" for a status this mapping doesn't recognize —
 * deliberately not the raw status string, so a genuinely unmapped value
 * reads as "we don't know" rather than leaking a raw backend enum token
 * into analyst-facing UI. In practice this only happens for the
 * placeholder case summary constructed when a `?case=` deep link points at
 * a case the workspace shell couldn't resolve from the initial queue fetch
 * (see `workspace-shell.tsx`) — a real `CaseListItem` from `GET /cases`
 * always carries one of the eight mapped values.
 */
export function getCaseStageLabel(status: string): string {
  return CASE_STAGE_LABELS[status] ?? "Unknown";
}
