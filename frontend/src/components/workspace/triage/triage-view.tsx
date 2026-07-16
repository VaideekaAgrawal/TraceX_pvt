import { AiPanel } from "@/components/workspace/triage/ai-panel";
import { AiRecommendationSlot } from "@/components/workspace/triage/ai-recommendation-slot";
import { AlertSummarySection } from "@/components/workspace/triage/alert-summary";
import { CustomerSnapshotSection } from "@/components/workspace/triage/customer-snapshot";
import { DecisionPanel } from "@/components/workspace/triage/decision-panel";
import { MoneyFlowSection } from "@/components/workspace/triage/money-flow";
import { NetworkRiskSection } from "@/components/workspace/triage/network-risk";
import { NotesPanel } from "@/components/workspace/triage/notes-panel";
import { PreviousAlertsSection } from "@/components/workspace/triage/previous-alerts";
import { SimilarCasesSection } from "@/components/workspace/triage/similar-cases";
import { TransactionSummarySection } from "@/components/workspace/triage/transaction-summary";

/**
 * L1 Triage screen — the 10 sections from `FRONTEND_PLAN.md` §3.3, each
 * wired to its own real endpoint via its own independent fetch (so one
 * section's failure never blocks the rest). Single scroll, clearly
 * sectioned via one `Card` per section. Mounted by `case-tab-content.tsx`
 * for the active/keep-alive tab — no fetching happens here itself, this
 * component is pure composition.
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
      <SimilarCasesSection caseId={caseId} />
      <AiRecommendationSlot />
      <NotesPanel caseId={caseId} />
      <DecisionPanel caseId={caseId} />
    </div>
  );
}
