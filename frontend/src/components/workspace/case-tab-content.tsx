"use client";

import { useEffect, useRef } from "react";

import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/components/dashboard/format";
import { getCaseStageLabel } from "@/lib/workspace/case-stage";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";

/**
 * A single case tab's body. `workspace-shell.tsx` mounts one of these per
 * `openTabIds` entry, always, toggling only visibility via CSS — never
 * conditional mount (see that file's docstring). No real L1/L2 content
 * yet (Phases 16–18); this exercises the real store fields Phase 15 does
 * own — cached case summary, notes draft, scroll position — rather than
 * being an empty placeholder div.
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

      <div className="flex flex-col gap-1.5">
        <label htmlFor={`notes-draft-${caseId}`} className="text-sm font-medium">
          Investigator Notes (draft)
        </label>
        <textarea
          id={`notes-draft-${caseId}`}
          value={tab.notesDraft}
          onChange={(e) => updateTabState(caseId, { notesDraft: e.target.value })}
          placeholder="Notes autosave and the real Notes panel arrive in Phase 16 — this draft survives a tab switch in the meantime."
          className="border-input min-h-24 rounded-lg border bg-transparent p-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium">Triage / Deep Investigation content</p>
        <div
          ref={scrollRef}
          onScroll={(e) => updateTabState(caseId, { scrollOffset: e.currentTarget.scrollTop })}
          className="h-48 overflow-y-auto rounded-lg border p-3 text-sm"
        >
          <p className="text-muted-foreground mb-2">
            The real L1 Triage / L2 Deep Investigation sections (alert summary, customer
            snapshot, money-flow graph, decision panel, etc.) are built in Phases 16–18 — this
            block exists in Phase 15 only to exercise scroll-position survival across a tab
            switch, per this phase&apos;s own verify requirement.
          </p>
          {Array.from({ length: 24 }, (_, i) => (
            <p key={i} className="text-muted-foreground border-t py-1.5 first:border-t-0">
              Placeholder content line {i + 1} of 24.
            </p>
          ))}
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
