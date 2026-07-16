"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { formatRiskScore } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { NetworkRiskResponse } from "@/lib/api/types";

/**
 * L1 Triage §7 — Network Risk. `GET .../network-risk` lazy-computes on
 * first view server-side; the "Recompute" button (§7b, explicitly required)
 * calls `POST .../network-risk/recompute` directly (not via the shared
 * `useTriageFetch` hook, since it's a write) and replaces local state with
 * the fresh response.
 */
export function NetworkRiskSection({ caseId }: { caseId: string }) {
  const url = `/api/cases/${encodeURIComponent(caseId)}/network-risk`;
  const { data, loading, error } = useTriageFetch<NetworkRiskResponse>(url);
  const [recomputing, setRecomputing] = useState(false);
  const [recomputeError, setRecomputeError] = useState<string | null>(null);
  const [override, setOverride] = useState<NetworkRiskResponse | null>(null);

  async function handleRecompute() {
    setRecomputing(true);
    setRecomputeError(null);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/network-risk/recompute`, {
        method: "POST",
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to recompute");
      }
      setOverride(body as NetworkRiskResponse);
    } catch (err) {
      setRecomputeError(err instanceof Error ? err.message : "Failed to recompute");
    } finally {
      setRecomputing(false);
    }
  }

  // A manual recompute's result always wins over whatever the lazy `GET`
  // last loaded — no need to also `refetch()` the `GET`, since `POST
  // .../recompute` already returns the identical fresh, now-persisted
  // shape (see that route's shared `_compute_and_respond` helper) and this
  // tab never remounts (Phase 15's keep-alive contract), so `override`
  // alone is a stable source of truth for the rest of this tab's lifetime.
  const shown = override ?? data;

  return (
    <TriageSection
      title="Network Risk"
      description="Structural risk signals from this case's linked-account network."
      loading={loading}
      error={error}
      action={
        <Button
          variant="outline"
          size="sm"
          onClick={() => void handleRecompute()}
          disabled={recomputing}
        >
          <RefreshCw className={recomputing ? "animate-spin" : undefined} />
          {recomputing ? "Recomputing…" : "Recompute"}
        </Button>
      }
    >
      {shown && (
        <div className="flex flex-col gap-3">
          <div>
            <p className="text-muted-foreground text-xs">Network Risk Score</p>
            <p className="text-2xl font-semibold">
              {shown.network_risk_score != null ? formatRiskScore(shown.network_risk_score) : "Not yet computed"}
            </p>
          </div>
          {shown.network_risk_reasons && Object.keys(shown.network_risk_reasons).length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Contributing Factors</p>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
                {Object.entries(shown.network_risk_reasons).map(([key, value]) => (
                  <div key={key}>
                    <dt className="text-muted-foreground text-xs">{humanizeKey(key)}</dt>
                    <dd className="font-medium">{formatReasonValue(value)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
          {/* A failed recompute must not blank out an already-loaded score
              (routing it through `TriageSection`'s `error` prop would hide
              `children` entirely, per that component's gating) — shown as
              its own inline message instead, next to the still-visible
              last-known-good data. */}
          {recomputeError && (
            <p className="text-destructive text-sm" role="alert">
              {recomputeError}
            </p>
          )}
        </div>
      )}
    </TriageSection>
  );
}

function humanizeKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatReasonValue(value: unknown): string {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}
