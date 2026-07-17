"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/components/dashboard/format";
import { cn } from "@/lib/utils";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { CaseListItem, SimilarCasesResponse } from "@/lib/api/types";

// Backend clamps `top_k` to 20 internally (`investigation/similar_cases.py`
// `_MAX_TOP_K`) regardless of what's requested — this is comfortably above
// that clamp so "expanded" genuinely means "the corpus's real top-k, no
// artificial frontend cap," matching the ROADMAP's "no top_k cap" wording,
// without needing to special-case an "omit the param" request shape.
const EXPANDED_TOP_K = 50;
const COMPACT_TOP_K = 3;

/**
 * L1 Triage §8 — Similar Historical Cases. Compact top-3 card by default;
 * expands in place to the corpus's full top-k (ROADMAP Phase 18) via the
 * same component — the roadmap explicitly calls for expanding out of this
 * existing card rather than building a second "full view" component.
 * Expand/collapse state is `tabState[caseId].similarCasesExpanded`, a
 * field Phase 15 already reserved on the tab store for exactly this.
 *
 * Each row is clickable — opens the referenced case as a real tab via
 * `GET /api/cases/{case_id}` (reachable for any case, per the backend's
 * `require_case_read_access`) + `useCaseTabStore`'s `openCase`, the same
 * convergence point the queue and the Dashboard `?case=` deep link already
 * use (`openCase` already handles "already open -> just focus" for us).
 */
export function SimilarCasesSection({ caseId }: { caseId: string }) {
  const expanded = useCaseTabStore((state) => state.tabState[caseId]?.similarCasesExpanded ?? false);
  const updateTabState = useCaseTabStore((state) => state.updateTabState);
  const openCase = useCaseTabStore((state) => state.openCase);

  const topK = expanded ? EXPANDED_TOP_K : COMPACT_TOP_K;
  const { data, loading, error } = useTriageFetch<SimilarCasesResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/similar-cases?top_k=${topK}`,
  );

  const [openingId, setOpeningId] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  async function handleOpen(targetCaseId: string) {
    setOpenError(null);
    setOpeningId(targetCaseId);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(targetCaseId)}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to open case");
      }
      openCase(body as CaseListItem);
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : "Failed to open case");
    } finally {
      setOpeningId(null);
    }
  }

  return (
    <TriageSection
      title="Similar Historical Cases"
      description={
        expanded
          ? "Full ranked list of the most similar closed/monitored cases, by RL feature-vector similarity."
          : "Top 3 most similar closed/monitored cases, by RL feature-vector similarity."
      }
      loading={loading}
      error={error}
      isEmpty={!!data && data.similar_cases.length === 0}
      emptyText="No similar historical cases found."
      action={
        <Button
          variant="outline"
          size="sm"
          onClick={() => updateTabState(caseId, { similarCasesExpanded: !expanded })}
        >
          {expanded ? "Show top 3" : "View all"}
        </Button>
      }
    >
      <div className="flex flex-col gap-2">
        {(data?.similar_cases ?? []).map((c) => (
          <button
            key={c.case_id}
            type="button"
            onClick={() => void handleOpen(c.case_id)}
            disabled={openingId === c.case_id}
            className={cn(
              "flex w-full flex-wrap items-center gap-2 rounded-lg border p-2 text-left text-sm transition-colors",
              "hover:bg-muted/50 disabled:cursor-not-allowed disabled:opacity-60",
            )}
          >
            <span className="font-medium">{c.case_id}</span>
            <Badge variant="outline">{(c.similarity * 100).toFixed(0)}% similar</Badge>
            {c.typology && <Badge variant="outline">{c.typology}</Badge>}
            {c.outcome && <span className="text-muted-foreground">{c.outcome}</span>}
            <span className="text-muted-foreground ml-auto text-xs">
              {openingId === c.case_id ? "Opening…" : formatDateTime(c.computed_at)}
            </span>
          </button>
        ))}
        {openError && (
          <p className="text-destructive text-xs" role="alert">
            {openError}
          </p>
        )}
      </div>
    </TriageSection>
  );
}
