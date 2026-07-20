"use client";

import { Badge } from "@/components/ui/badge";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import type { AuditLogListResponse } from "@/lib/api/types";

/**
 * "Activity" tab inside the floating AI widget — the audit-thread
 * visibility gap flagged on ROADMAP Phase 19's own Verify line ("confirm
 * the audit log shows the full thread... the frontend should make that
 * thread visible, e.g. via the My Center audit view, not just functional").
 * Before this panel, nothing in the frontend ever surfaced an
 * `ai_interaction_created` audit row: `notification-bell.tsx` deliberately
 * curates a fixed allowlist (`case_assigned`/`case_reassigned`/`escalated`/
 * `decision_changed`) that excludes it by design.
 *
 * Reuses the existing `GET /audit-log` surface (`audit-client.ts`,
 * `app/api/audit-log/route.ts`, ROADMAP Phase 14) unchanged — no new
 * backend route — via the same `useTriageFetch` hook every L1 section
 * component already uses, rather than a hand-rolled effect (its own
 * docstring documents the exact `set-state-in-effect` lint constraint a
 * naive version of this panel hit first).
 *
 * Deliberately minimal, and honest about the limit: `audit_log.details` is
 * `null` for this action (`AiInteractionRepository.create` doesn't pass a
 * `details` dict — the actual response text/facts/tools_called live in
 * `ai_interactions`, not `audit_log`), so this renders occurrence metadata
 * (when, and the `ai_interactions.id` via `entity_id` a regulator or admin
 * could cross-reference) — NOT the AI's response text inline. Rendering
 * the full response would need a new backend GET-by-id-list-for-case route
 * over `ai_interactions` itself, real additional scope beyond this pass;
 * flagged here rather than faked with a misleading "full thread" label.
 */
export function AuditThreadPanel({ caseId }: { caseId: string | null }) {
  const url = caseId
    ? `/api/audit-log?${new URLSearchParams({ case_id: caseId, action: "ai_interaction_created", limit: "50" }).toString()}`
    : null;
  const { data, loading, error } = useTriageFetch<AuditLogListResponse>(url);
  const items = data?.items ?? [];

  if (!caseId) {
    return (
      <p className="text-muted-foreground text-sm">
        No case open — open a case to see its AI activity.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-muted-foreground text-xs">
        Every AI recommendation/challenge/Copilot call recorded against this case, from the audit
        log&apos;s tamper-evident hash chain. Shows when each interaction happened, not its content —
        the full record (facts, cited rules, response text) lives in <code>ai_interactions</code>,
        referenced here by id.
      </p>

      {loading && <p className="text-muted-foreground text-xs">Loading…</p>}
      {error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}
      {!loading && !error && items.length === 0 && (
        <p className="text-muted-foreground text-sm">No AI activity recorded for this case yet.</p>
      )}

      <div className="flex flex-col gap-1.5">
        {items.map((item) => (
          <div key={item.id} className="flex items-center justify-between gap-2 rounded-lg border p-2 text-xs">
            <div className="min-w-0">
              <p className="font-medium">AI interaction</p>
              <p className="text-muted-foreground">{new Date(item.created_at).toLocaleString()}</p>
            </div>
            <Badge variant="outline" className="shrink-0 font-normal">
              #{item.entity_id ?? "?"}
            </Badge>
          </div>
        ))}
      </div>
    </div>
  );
}
