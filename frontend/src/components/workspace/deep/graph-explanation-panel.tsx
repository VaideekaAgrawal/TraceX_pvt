"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { AiGeneratedBanner } from "@/components/workspace/ai-generated-banner";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { GraphExplanationResponse } from "@/lib/api/types";

/**
 * L2 — AI Investigation Graph explanation, `GET .../accounts/{account_id}/
 * graph-explanation` (new this pass, `backend/api/routes/l2.py::
 * get_graph_explanation`). Mounted right after `InvestigationGraphSection`
 * in `deep-view.tsx`, since it's explaining that same graph: plain-language
 * narrative of likely source/mule/sink roles, whether there's a transaction
 * cycle, and where money is concentrating — grounded only in server-
 * computed facts about the account's own graph, no narration/purpose text
 * read (`orchestration/graph_explanation.py` mirrors `account_explanation.
 * py`'s guardrail pattern exactly).
 *
 * Scoped to `account_id` directly (one explanation per account per case),
 * unlike `pattern-explanation-panel.tsx`'s per-alert shape — no alert
 * selector needed here. Same AI-panel treatment as every other AI panel in
 * this app: shared `AiGeneratedBanner`, cached indicator, Regenerate button
 * (`force=true` + a nonce), loading/error/empty states via `TriageSection`.
 */
export function GraphExplanationSection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const [regenNonce, setRegenNonce] = useState(0);
  const url =
    `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/graph-explanation` +
    (regenNonce > 0 ? `?force=true&_r=${regenNonce}` : "");
  const { data, loading, error } = useTriageFetch<GraphExplanationResponse>(url);

  return (
    <TriageSection
      title="AI Investigation Graph Explanation"
      description="AI-generated narrative of the structural money-flow patterns in the graph above — likely source/mule/sink roles, transaction cycles, and flow concentration — grounded only in this account's own persisted graph facts."
      loading={loading}
      error={error}
      isEmpty={false}
    >
      {data && (
        <div className="flex flex-col gap-2">
          <AiGeneratedBanner model={data.model} generatedAt={data.generated_at} cached={data.cached} />
          <p className="text-sm leading-relaxed">{data.explanation}</p>
          <div>
            <Button variant="outline" size="sm" onClick={() => setRegenNonce((n) => n + 1)} disabled={loading}>
              <RefreshCw />
              Regenerate
            </Button>
          </div>
        </div>
      )}
    </TriageSection>
  );
}
