"use client";

import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/components/dashboard/format";
import { DeepView } from "@/components/workspace/deep/deep-view";
import { DecisionPanel } from "@/components/workspace/triage/decision-panel";
import { TriageView } from "@/components/workspace/triage/triage-view";
import { useAuth } from "@/lib/auth/auth-provider";
import { getCaseStageLabel } from "@/lib/workspace/case-stage";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import type { CaseListItem } from "@/lib/api/types";

/**
 * A single case tab's body. `workspace-shell.tsx` mounts one of these per
 * `openTabIds` entry, always, toggling only visibility via CSS — never
 * conditional mount (see that file's docstring). Branches on `tab.
 * activeView` between the real L1 Triage screen (Phase 16, `components/
 * workspace/triage/triage-view.tsx`) and the L2 Deep Investigation screen
 * (Phase 17, `components/workspace/deep/deep-view.tsx`).
 *
 * `activeView` defaults from the case's own status (`getDefaultActiveView`,
 * `case-stage.ts`) whenever a tab opens or its cached status changes — see
 * `case-tab-store.ts`'s `openCase`/`defaultTabState` and `decision-panel.
 * tsx`'s post-decision update. The toggle below (ROADMAP Phase 17 judgment
 * call, documented there) lets an investigator switch either direction
 * regardless of that default — e.g. peeking at the full graph on a case
 * that hasn't been escalated yet, or double-checking the L1 summary on one
 * that has (though Deep Investigation's own collapsed `TriageSummaryCollapsible`
 * already covers most of that second case without switching away).
 *
 * `DecisionPanel` is mounted here, in this same always-visible zone (with
 * the `<dl>` summary block below), NOT inside `triage-view.tsx`'s
 * `activeView`-toggled scroll container — it must stay visible and
 * functional regardless of whether the tab is showing Triage or Deep
 * Investigation, so switching between them never hides the only place to
 * act on a case.
 */
export function CaseTabContent({ caseId }: { caseId: string }) {
  const tab = useCaseTabStore((state) => state.tabState[caseId]);
  const activeTabId = useCaseTabStore((state) => state.activeTabId);
  const updateTabState = useCaseTabStore((state) => state.updateTabState);
  const { user } = useAuth();

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

  // Auto-fires `POST .../start` (`ASSIGNED -> IN_PROGRESS`) exactly once
  // when an Investigator opens their OWN freshly-assigned case — closes the
  // gap where clicking Escalate on a just-assigned case immediately hit the
  // FSM-illegal `ASSIGNED -> ESCALATED` transition (the real fix is
  // `IN_PROGRESS` being reachable at all). Deliberately does NOT fire for
  // Admin/Compliance browsing someone else's assigned case — only the
  // assignee's own act of opening it should silently mutate case state.
  // Guarded by a ref `Set` keyed by `caseId` (same fire-once-per-tab
  // pattern as `workspace-shell.tsx`'s `resolvedDeepLink` ref) so it never
  // double-fires across re-renders. Best-effort: a 409 (something else
  // already transitioned the case) or a network failure is swallowed
  // silently — the cached tab status catches up on the next real
  // fetch/decision regardless, nothing else depends on this succeeding.
  const autoStartedRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!tab || !user) return;
    if (user.role !== "INVESTIGATOR") return;
    if (tab.summary.status !== "ASSIGNED") return;
    if (tab.summary.assigned_to !== user.user_id) return;
    if (autoStartedRef.current.has(caseId)) return;
    autoStartedRef.current.add(caseId);

    void (async () => {
      try {
        const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/start`, { method: "POST" });
        if (!res.ok) return;
        const result = (await res.json()) as CaseListItem;
        const currentSummary = useCaseTabStore.getState().tabState[caseId]?.summary;
        if (currentSummary) {
          updateTabState(caseId, { summary: { ...currentSummary, status: result.status } });
        }
      } catch {
        // best-effort only, see docstring above.
      }
    })();
  }, [tab, user, caseId, updateTabState]);

  if (!tab) return null;

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="font-heading text-lg font-semibold">{caseId}</h2>
        <Badge variant="outline">{getCaseStageLabel(tab.summary.status)}</Badge>
        <Badge variant="outline">{tab.summary.priority || "—"}</Badge>

        <div className="ml-auto flex items-center gap-1 rounded-lg border p-0.5">
          <Button
            variant={tab.activeView === "triage" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => updateTabState(caseId, { activeView: "triage" })}
          >
            Triage
          </Button>
          <Button
            variant={tab.activeView === "deep" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => updateTabState(caseId, { activeView: "deep" })}
          >
            Deep Investigation
          </Button>
        </div>
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

      <DecisionPanel caseId={caseId} />

      <div
        ref={scrollRef}
        onScroll={(e) => updateTabState(caseId, { scrollOffset: e.currentTarget.scrollTop })}
        className="max-h-[75vh] overflow-y-auto rounded-lg border p-3"
      >
        {/* Both views stay mounted; only visibility toggles via CSS — same
            keep-alive convention `workspace-shell.tsx` uses one level up for
            tabs themselves, so switching Triage<->Deep Investigation doesn't
            discard Deep Investigation's own local state (graph filters,
            selected node/edge, transaction explorer scope/pagination, etc.). */}
        <div className={tab.activeView === "deep" ? undefined : "hidden"}>
          <DeepView caseId={caseId} accountId={tab.summary.primary_account_id} />
        </div>
        <div className={tab.activeView === "triage" ? undefined : "hidden"}>
          <TriageView caseId={caseId} accountId={tab.summary.primary_account_id} />
        </div>
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
