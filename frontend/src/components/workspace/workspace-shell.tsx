"use client";

import { useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CaseQueue } from "@/components/workspace/case-queue";
import { CaseTabBar } from "@/components/workspace/case-tab-bar";
import { CaseTabContent } from "@/components/workspace/case-tab-content";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import type { CaseListItem, CaseListResponse } from "@/lib/api/types";

/**
 * Owns the Zustand tab store's two entry points converging: the queue list
 * below calls `openCase` directly (`case-queue.tsx`), and this component
 * resolves a `?case=` deep link (e.g. from a Phase-14 Dashboard row) on
 * mount and calls the exact same `openCase` action for it — per the Phase
 * 15 requirement that both entry points converge on one tab-open path.
 *
 * Judgment call: `GET /cases` (the only case-list endpoint this phase has)
 * is role-scoped server-side and may not include the case a `?case=` link
 * points at (e.g. an Investigator deep-linking to a case not assigned to
 * them, or any case outside the current queue page). There is no
 * `GET /cases/{case_id}` single-case lookup route to fall back to yet — so
 * when the deep-linked case isn't in the initial queue fetch, this opens a
 * placeholder tab with only `case_id` known and the rest of `CaseListItem`
 * left as neutral/empty values. `case-stage.ts::getCaseStageLabel` and this
 * component's own rendering treat an empty/unmapped status as "Unknown"
 * rather than guessing a stage, so the placeholder doesn't assert anything
 * false. Later phases (16+, once case-detail routes exist) can replace this
 * with a real single-case fetch.
 */
export function WorkspaceShell({ initialQueue }: { initialQueue: CaseListResponse }) {
  const searchParams = useSearchParams();
  const openCase = useCaseTabStore((state) => state.openCase);
  const resolvedDeepLink = useRef<string | null>(null);

  useEffect(() => {
    const caseId = searchParams.get("case");
    if (!caseId || resolvedDeepLink.current === caseId) return;
    resolvedDeepLink.current = caseId;

    const known = initialQueue.items.find((item) => item.case_id === caseId);
    if (known) {
      openCase(known);
      return;
    }

    const placeholder: CaseListItem = {
      case_id: caseId,
      primary_account_id: "",
      status: "",
      priority: "",
      assigned_to: null,
      updated_at: "",
    };
    openCase(placeholder);
  }, [searchParams, initialQueue, openCase]);

  const openTabIds = useCaseTabStore((state) => state.openTabIds);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="font-heading text-xl font-semibold">Investigation Workspace</h1>
        <p className="text-muted-foreground text-sm">
          Your case queue — select a case to open it as a tab below.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Your Cases</CardTitle>
        </CardHeader>
        <CardContent>
          <CaseQueue initialData={initialQueue} />
        </CardContent>
      </Card>

      <div className="rounded-xl border">
        <CaseTabBar />
        {openTabIds.map((caseId) => (
          <CaseTabContentWrapper key={caseId} caseId={caseId} />
        ))}
      </div>
    </div>
  );
}

// All `openTabIds` are rendered as siblings here, always mounted — this
// wrapper is the actual keep-alive visibility toggle (CSS `hidden`/`block`
// only, never `{activeTabId === id && <Tab/>}`, which would unmount the
// inactive tab and lose its scroll position / draft state).
function CaseTabContentWrapper({ caseId }: { caseId: string }) {
  const activeTabId = useCaseTabStore((state) => state.activeTabId);
  return (
    <div className={activeTabId === caseId ? "block" : "hidden"}>
      <CaseTabContent caseId={caseId} />
    </div>
  );
}
