"use client";

import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { useRole } from "@/lib/auth/auth-provider";
import type { ModelMetricsResponse } from "@/lib/api/types";

/**
 * ROADMAP Phase 22 — model governance surfacing (`SYSTEM_DEVELOPMENT_PLAN.md`
 * §5's RBI model-governance question), a small unobtrusive "model v{n},
 * trained {date}" indicator near the Network Risk / detection-derived
 * panels. Backed by `GET /model-metrics` (`backend/api/routes/
 * governance.py`, ROADMAP Phase 12 backend, done), which is Admin/
 * Compliance only server-side — `useRole()` is a UX courtesy here (the
 * backend enforces independently and wins, per `auth-provider.tsx`), used
 * to skip the fetch entirely for an Investigator rather than let every one
 * of them draw a guaranteed 403 on every Triage view. Visual template
 * matches `ai-generated-banner.tsx` (small `Badge` + muted caption) — not
 * that component itself, since this isn't AI-generated content. No
 * `caseId` prop — `/model-metrics` is a global governance snapshot, not
 * case-scoped, unlike every other Triage section it's mounted alongside.
 */
export function ModelGovernanceIndicator() {
  const role = useRole();
  const isAdmin = role === "ADMIN_COMPLIANCE";
  const { data, loading, error } = useTriageFetch<ModelMetricsResponse>(
    isAdmin ? "/api/model-metrics" : null,
  );

  // Silent for an Investigator — this indicator is compliance-facing, not
  // an Investigator-relevant fact, so it never even attempts the fetch.
  if (!isAdmin) return null;

  if (loading) {
    return <p className="text-muted-foreground text-xs">Loading model info…</p>;
  }
  if (error) {
    return (
      <p className="text-destructive text-xs" role="alert">
        Model governance info unavailable: {error}
      </p>
    );
  }
  if (!data || data.models.length === 0) {
    return <p className="text-muted-foreground text-xs">No active model registered.</p>;
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      {data.models.map((m) => (
        <span key={`${m.model_type}-${m.version}`} className="flex items-center gap-1.5">
          <Badge variant="outline">{m.model_type}</Badge>
          <span>
            v{m.version} · {m.trained_at ? `trained ${formatDateTime(m.trained_at)}` : "training date unknown"}
          </span>
        </span>
      ))}
    </div>
  );
}
