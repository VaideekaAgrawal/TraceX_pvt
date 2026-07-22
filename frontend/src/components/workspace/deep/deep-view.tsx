"use client";

import { useState } from "react";

import { BehaviorAnalysisSection } from "@/components/workspace/deep/behavior-analysis";
import { CustomerProfileSection } from "@/components/workspace/deep/customer-profile";
import { EvidencePanel } from "@/components/workspace/deep/evidence-panel";
import { GraphExplanationSection } from "@/components/workspace/deep/graph-explanation-panel";
import { GraphReplaySection } from "@/components/workspace/deep/graph-replay";
import { InvestigationGraphSection } from "@/components/workspace/deep/investigation-graph";
import { InvestigationTimelineSection } from "@/components/workspace/deep/investigation-timeline";
import { PatternExplanationSection } from "@/components/workspace/deep/pattern-explanation-panel";
import { RelationshipExplorerSection } from "@/components/workspace/deep/relationship-explorer";
import { TransactionExplorerSection } from "@/components/workspace/deep/transaction-explorer";
import { TriageSummaryCollapsible } from "@/components/workspace/deep/triage-summary-collapsible";

/**
 * L2 Deep Investigation screen — mounted by `case-tab-content.tsx` when
 * `tab.activeView === "deep"`, mirroring `triage/triage-view.tsx`'s "pure
 * composition, each section owns its own fetch" shape. `selectedTxnId`
 * (ROADMAP Phase 17) and `selectedAccountId` (ROADMAP Phase 18) are lifted
 * here (not into any one section) so:
 *   - the Investigation Graph and Investigation Timeline can correlate a
 *     click in either direction via the shared `txn_id` key, per the
 *     designed data contract (`investigation/timeline.py`'s docstring) —
 *     no extra backend call for this;
 *   - the Evidence panel's "bookmark selected transaction/account" quick
 *     actions can read whatever's currently selected in the graph without
 *     any component needing to know about evidence specifically.
 *
 * `isActive` (`case-tab-content.tsx`'s `tab.activeView === "deep"`) is
 * forwarded only to the three cytoscape-based sections (Investigation
 * Graph, Relationship Explorer, Graph Replay) — this view stays mounted
 * (keep-alive) even while hidden behind Triage, and each of those graphs'
 * `fit: true` layout call corrupts computed node positions (not just the
 * camera) when it runs against a 0-size `display:none` container, so each
 * one gates/re-runs its layout on this prop rather than running it
 * unconditionally on mount (see each section's own layout-effect comment).
 */
export function DeepView({
  caseId,
  accountId,
  isActive,
}: {
  caseId: string;
  accountId: string;
  isActive: boolean;
}) {
  const [selectedTxnId, setSelectedTxnId] = useState<string | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);

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
        selectedAccountId={selectedAccountId}
        onSelectAccount={setSelectedAccountId}
        isActive={isActive}
      />
      <GraphExplanationSection caseId={caseId} accountId={accountId} />
      <InvestigationTimelineSection
        caseId={caseId}
        accountId={accountId}
        selectedTxnId={selectedTxnId}
        onSelectTxn={setSelectedTxnId}
      />
      <GraphReplaySection caseId={caseId} accountId={accountId} isActive={isActive} />
      <RelationshipExplorerSection caseId={caseId} isActive={isActive} />
      <TransactionExplorerSection caseId={caseId} accountId={accountId} />
      <CustomerProfileSection caseId={caseId} accountId={accountId} />
      <BehaviorAnalysisSection caseId={caseId} accountId={accountId} />
      <PatternExplanationSection caseId={caseId} />
      <EvidencePanel caseId={caseId} selectedTxnId={selectedTxnId} selectedAccountId={selectedAccountId} />
    </div>
  );
}
