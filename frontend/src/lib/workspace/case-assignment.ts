import type { CaseListItem } from "@/lib/api/types";

/**
 * Whether `summary` (a cached case-tab summary) is currently assigned to
 * `userId`. Shared by `triage/decision-panel.tsx` (gates its read-only
 * message) and `ai-widget/ai-widget.tsx` (gates `/recommendations`
 * access) — both independently re-derived this exact `assigned_to ===`
 * check before extraction; kept here so the assignment rule can't drift
 * between the two. Returns `false` (never assigned) when `summary` hasn't
 * loaded yet — callers that need to distinguish "not loaded" from
 * "loaded, not assigned to me" still check `summary != null` themselves.
 */
export function isAssignedToUser(
  summary: Pick<CaseListItem, "assigned_to"> | null | undefined,
  userId: string | null | undefined,
): boolean {
  return summary != null && summary.assigned_to === (userId ?? null);
}
