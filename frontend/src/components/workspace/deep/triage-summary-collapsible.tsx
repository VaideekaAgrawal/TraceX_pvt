"use client";

import { ChevronDownIcon } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { TriageView } from "@/components/workspace/triage/triage-view";

/**
 * Wraps Phase 16's own `TriageView` composition, collapsed by default,
 * inside the Deep Investigation view (ROADMAP Phase 17 item 1) — reuses
 * every L1 section as-is rather than reimplementing any of them. This is
 * what lets an investigator glance back at the full L1 triage picture
 * (alert summary, AI explanation, customer snapshot, money flow, decision
 * panel, etc.) without leaving Deep Investigation mode.
 */
export function TriageSummaryCollapsible({ caseId, accountId }: { caseId: string; accountId: string }) {
  return (
    <Card>
      <Collapsible defaultOpen={false}>
        <CardHeader>
          <CollapsibleTrigger className="group flex w-full items-center justify-between gap-2 text-left">
            <CardTitle>Triage Summary (L1)</CardTitle>
            <ChevronDownIcon className="text-muted-foreground size-4 shrink-0 transition-transform group-data-[panel-open]:rotate-180" />
          </CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent>
          <CardContent>
            <TriageView caseId={caseId} accountId={accountId} />
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}
