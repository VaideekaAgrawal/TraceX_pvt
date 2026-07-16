"use client";

import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/components/dashboard/format";
import { TriageView } from "@/components/workspace/triage/triage-view";
import { getCaseStageLabel } from "@/lib/workspace/case-stage";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";

/**
 * A single case tab's body. `workspace-shell.tsx` mounts one of these per
 * `openTabIds` entry, always, toggling only visibility via CSS — never
 * conditional mount (see that file's docstring). Renders the real L1
 * Triage screen (Phase 16, `components/workspace/triage/triage-view.tsx`);
 * L2 Deep Investigation content arrives in Phases 17–18 as a second
 * `activeView` this same tab switches into (`tab.activeView`, still
 * `"triage"`-only for now — no UI to change it yet since there's nothing
 * to switch to).
 */
export function CaseTabContent({ caseId }: { caseId: string }) {
  const tab = useCaseTabStore((state) => state.tabState[caseId]);
  const activeTabId = useCaseTabStore((state) => state.activeTabId);
  const updateTabState = useCaseTabStore((state) => state.updateTabState);

  const scrollRef = useRef<HTMLDivElement>(null);
  const wasActiveRef = useRef(false);
  const isActive = activeTabId === caseId;

  // Restores this tab's saved scroll position exactly once per "became
  // active" transition (not on every scrollOffset change, which would
  // otherwise fight the user's own scrolling — see the `wasActiveRef`
  // guard). Keep-alive mounting means this container never actually
  // unmounts, so a plain effect + ref is enough; no need to persist
  // anywhere beyond this store.
  useEffect(() => {
    if (isActive && !wasActiveRef.current && scrollRef.current && tab) {
      scrollRef.current.scrollTop = tab.scrollOffset;
    }
    wasActiveRef.current = isActive;
  }, [isActive, tab]);

  if (!tab) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-heading text-lg font-semibold">{caseId}</h2>
        <Badge variant="outline">{getCaseStageLabel(tab.summary.status)}</Badge>
        <Badge variant="outline">{tab.summary.priority || "—"}</Badge>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <SummaryField label="Primary Account" value={tab.summary.primary_account_id || "—"} />
        <SummaryField label="Status" value={tab.summary.status || "Unknown"} />
        <SummaryField
          label="Assigned To"
          value={tab.summary.assigned_to ?? "Unassigned"}
        />
        <SummaryField
          label="Last Updated"
          value={tab.summary.updated_at ? formatDateTime(tab.summary.updated_at) : "—"}
        />
      </dl>

      <div
        ref={scrollRef}
        onScroll={(e) => updateTabState(caseId, { scrollOffset: e.currentTarget.scrollTop })}
        className="max-h-[75vh] overflow-y-auto rounded-lg border p-3"
      >
        <TriageView caseId={caseId} accountId={tab.summary.primary_account_id} />
      </div>
    </div>
  );
}

function SummaryField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
