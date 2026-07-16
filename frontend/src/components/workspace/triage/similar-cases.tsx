"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { SimilarCasesResponse } from "@/lib/api/types";

/**
 * L1 Triage §8 — Similar Historical Cases, compact top-3 card only this
 * phase (per the task spec — no expanded L2 view until Phase 17). The
 * "View all" affordance below is deliberately non-functional (disabled,
 * not a dead link) rather than omitted, so the eventual L2 expansion has an
 * obvious anchor point.
 */
export function SimilarCasesSection({ caseId }: { caseId: string }) {
  const { data, loading, error } = useTriageFetch<SimilarCasesResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/similar-cases?top_k=3`,
  );

  return (
    <TriageSection
      title="Similar Historical Cases"
      description="Top 3 most similar closed/monitored cases, by RL feature-vector similarity."
      loading={loading}
      error={error}
      isEmpty={!!data && data.similar_cases.length === 0}
      emptyText="No similar historical cases found."
      action={
        <Button variant="outline" size="sm" disabled title="Full view arrives with Deep Investigation (Phase 17)">
          View all
        </Button>
      }
    >
      <div className="flex flex-col gap-2">
        {(data?.similar_cases ?? []).map((c) => (
          <div key={c.case_id} className="flex flex-wrap items-center gap-2 rounded-lg border p-2 text-sm">
            <span className="font-medium">{c.case_id}</span>
            <Badge variant="outline">{(c.similarity * 100).toFixed(0)}% similar</Badge>
            {c.typology && <Badge variant="outline">{c.typology}</Badge>}
            {c.outcome && <span className="text-muted-foreground">{c.outcome}</span>}
            <span className="text-muted-foreground ml-auto text-xs">{formatDateTime(c.computed_at)}</span>
          </div>
        ))}
      </div>
    </TriageSection>
  );
}
