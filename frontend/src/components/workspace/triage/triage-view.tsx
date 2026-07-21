import { AiPanel } from "@/components/workspace/triage/ai-panel";
import { AlertSummarySection } from "@/components/workspace/triage/alert-summary";
import { CustomerSnapshotSection } from "@/components/workspace/triage/customer-snapshot";
import { ModelGovernanceIndicator } from "@/components/workspace/model-governance-indicator";
import { MoneyFlowSection } from "@/components/workspace/triage/money-flow";
import { NetworkRiskSection } from "@/components/workspace/triage/network-risk";
import { PreviousAlertsSection } from "@/components/workspace/triage/previous-alerts";
import { SimilarCasesSection } from "@/components/workspace/triage/similar-cases";
import { TransactionSummarySection } from "@/components/workspace/triage/transaction-summary";

/**
 * L1 Triage screen — 7 of the sections from `FRONTEND_PLAN.md` §3.3, each
 * wired to its own real endpoint via its own independent fetch (so one
 * section's failure never blocks the rest). Single scroll, clearly
 * sectioned via one `Card` per section. Mounted by `case-tab-content.tsx`
 * for the active/keep-alive tab — no fetching happens here itself, this
 * component is pure composition.
 *
 * `DecisionPanel` and `NotesPanel` are deliberately NOT mounted here —
 * both are lifted to `case-tab-content.tsx`'s always-visible zone so they
 * stay reachable from both Triage and Deep Investigation without
 * remounting on the L1/L2 toggle (see that file's docstring). The old
 * static "AI Recommendation" slot is gone too — superseded by the real,
 * functional floating AI widget (`components/workspace/ai-widget/`),
 * global across the whole workspace rather than one more per-tab section.
 */
export function TriageView({ caseId, accountId }: { caseId: string; accountId: string }) {
  if (!accountId) {
    return (
      <p className="text-muted-foreground text-sm">
        This case has no known primary account yet — triage sections that require one can&apos;t
        load.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <AlertSummarySection caseId={caseId} />
      <AiPanel caseId={caseId} accountId={accountId} />
      <CustomerSnapshotSection caseId={caseId} accountId={accountId} />
      <MoneyFlowSection caseId={caseId} accountId={accountId} />
      <TransactionSummarySection caseId={caseId} accountId={accountId} />
      <PreviousAlertsSection caseId={caseId} accountId={accountId} />
      <NetworkRiskSection caseId={caseId} />
      <ModelGovernanceIndicator />
      <SimilarCasesSection caseId={caseId} />
    </div>
  );
}
