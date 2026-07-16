"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import type { ExplanationResponse } from "@/lib/api/types";

/**
 * L1 Triage AI panel — account-level explanation only (`GET .../explanation`)
 * per `docs/FRONTEND_ROADMAP.md`'s Phase 16 checklist. Pattern-level
 * explanation (`GET .../alerts/{alert_id}/pattern-explanation`) is L2 scope
 * (Phase 17), not built here.
 */
export function AiPanel({ caseId, accountId }: { caseId: string; accountId: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI Explanation</CardTitle>
      </CardHeader>
      <CardContent>
        <AccountExplanationTab caseId={caseId} accountId={accountId} />
      </CardContent>
    </Card>
  );
}

function AiGeneratedBanner({ model, generatedAt, cached }: { model: string; generatedAt: string; cached: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <Badge variant="outline" className="border-primary/40 bg-primary/5 text-primary">
        AI-Generated
      </Badge>
      <span>
        {model} · {formatDateTime(generatedAt)}
        {cached ? " · cached" : ""}
      </span>
    </div>
  );
}

function AccountExplanationTab({ caseId, accountId }: { caseId: string; accountId: string }) {
  const [regenNonce, setRegenNonce] = useState(0);
  const url =
    `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/explanation` +
    (regenNonce > 0 ? `?force=true&_r=${regenNonce}` : "");
  const { data, loading, error } = useTriageFetch<ExplanationResponse>(url);

  return (
    <div className="flex flex-col gap-2">
      {loading && <p className="text-muted-foreground text-sm">Generating explanation…</p>}
      {!loading && error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}
      {!loading && !error && data && (
        <>
          <AiGeneratedBanner model={data.model} generatedAt={data.generated_at} cached={data.cached} />
          <p className="text-sm leading-relaxed">{data.explanation}</p>
          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRegenNonce((n) => n + 1)}
              disabled={loading}
            >
              <RefreshCw />
              Regenerate
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
