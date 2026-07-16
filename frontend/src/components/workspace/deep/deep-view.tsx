"use client";

import { useState } from "react";

import { BehaviorAnalysisSection } from "@/components/workspace/deep/behavior-analysis";
import { CustomerProfileSection } from "@/components/workspace/deep/customer-profile";
import { InvestigationGraphSection } from "@/components/workspace/deep/investigation-graph";
import { InvestigationTimelineSection } from "@/components/workspace/deep/investigation-timeline";
import { TransactionExplorerSection } from "@/components/workspace/deep/transaction-explorer";
import { TriageSummaryCollapsible } from "@/components/workspace/deep/triage-summary-collapsible";

/**
 * L2 Deep Investigation screen (ROADMAP Phase 17) — mounted by
 * `case-tab-content.tsx` when `tab.activeView === "deep"`, mirroring
 * `triage/triage-view.tsx`'s "pure composition, each section owns its own
 * fetch" shape. `selectedTxnId` is lifted here (not into any one section)
 * so the Investigation Graph and Investigation Timeline can correlate a
 * click in either direction via the shared `txn_id` key, per the designed
 * data contract (`investigation/timeline.py`'s docstring) — no extra
 * backend call for this.
 */
export function DeepView({ caseId, accountId }: { caseId: string; accountId: string }) {
  const [selectedTxnId, setSelectedTxnId] = useState<string | null>(null);

  if (!accountId) {
    return (
      <p className="text-muted-foreground text-sm">
        This case has no known primary account yet — deep investigation sections that require one
        can&apos;t load.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <TriageSummaryCollapsible caseId={caseId} accountId={accountId} />
      <InvestigationGraphSection
        caseId={caseId}
        accountId={accountId}
        selectedTxnId={selectedTxnId}
        onSelectTxn={setSelectedTxnId}
      />
      <InvestigationTimelineSection
        caseId={caseId}
        accountId={accountId}
        selectedTxnId={selectedTxnId}
        onSelectTxn={setSelectedTxnId}
      />
      <TransactionExplorerSection caseId={caseId} accountId={accountId} />
      <CustomerProfileSection caseId={caseId} accountId={accountId} />
      <BehaviorAnalysisSection caseId={caseId} accountId={accountId} />
    </div>
  );
}
