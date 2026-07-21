"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Inbox, PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { AiWidget } from "@/components/workspace/ai-widget/ai-widget";
import { CaseQueue } from "@/components/workspace/case-queue";
import { CaseTabBar } from "@/components/workspace/case-tab-bar";
import { CaseTabContent } from "@/components/workspace/case-tab-content";
import { cn } from "@/lib/utils";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import { useOpenCaseTab } from "@/lib/workspace/use-open-case-tab";
import type { CaseListResponse } from "@/lib/api/types";

/**
 * Owns the Zustand tab store's two entry points converging: the queue list
 * below calls `openCase` directly (`case-queue.tsx`), and this component
 * resolves a `?case=` deep link (e.g. from a Phase-14 Dashboard row) on
 * mount and calls the exact same `openCase` action for it — per the Phase
 * 15 requirement that both entry points converge on one tab-open path.
 *
 * `GET /cases` (the queue list) is role-scoped server-side and may not
 * include the case a `?case=` link points at (e.g. a case outside the
 * current queue page, or — for Admin/Compliance — one not assigned to
 * anyone yet). Phase 22: previously this fell back to a local placeholder
 * tab (`case_id` only, rest of `CaseListItem` left blank, rendered as
 * "Unknown") because no single-case lookup route existed. `GET
 * /cases/{case_id}` now exists and is already used by `similar-cases.tsx`/
 * `previous-alerts.tsx` via `useOpenCaseTab` — reused here instead of a
 * second, permanently-stale placeholder path. `openCase` also flips
 * `centerView` to `"tabs"` as part of this resolution — a deep link should
 * land you on the case, not the queue.
 *
 * Layout: a collapsible left column holds a "Queue" nav entry plus the
 * vertical open-case tab rail (`CaseTabBar`); a center column shows either
 * the full case queue table (`centerView === "queue"`, or whenever no tabs
 * are open regardless of `centerView` — there's nothing to show as "tabs"
 * either way) or the active tab's `CaseTabContent`, exactly like clicking a
 * case tab. The queue table itself is NOT a left-column fixture anymore —
 * it's one more thing you navigate to in the center panel, same as any
 * case. The keep-alive rendering (`CaseTabContentWrapper`, CSS
 * `hidden`/`block` toggle, every open tab always mounted) is unchanged.
 *
 * `AiWidget` is mounted once here, globally — it reads `activeTabId`/
 * `tabState`/`centerView` directly off the same store, so it always knows
 * which case (if any) it's currently scoped to regardless of which case tab
 * or the queue is showing underneath it.
 */
export function WorkspaceShell({ initialQueue }: { initialQueue: CaseListResponse }) {
  const searchParams = useSearchParams();
  const openCase = useCaseTabStore((state) => state.openCase);
  const resolvedDeepLink = useRef<string | null>(null);
  const { openError: deepLinkError, handleOpen: openCaseById } = useOpenCaseTab();

  useEffect(() => {
    const caseId = searchParams.get("case");
    if (!caseId || resolvedDeepLink.current === caseId) return;
    resolvedDeepLink.current = caseId;

    const known = initialQueue.items.find((item) => item.case_id === caseId);
    if (known) {
      openCase(known);
      return;
    }

    void openCaseById(caseId);
  }, [searchParams, initialQueue, openCase, openCaseById]);

  const openTabIds = useCaseTabStore((state) => state.openTabIds);
  const centerView = useCaseTabStore((state) => state.centerView);
  const showQueue = useCaseTabStore((state) => state.showQueue);

  const [collapsed, setCollapsed] = useState(false);

  const showQueueInCenter = centerView === "queue" || openTabIds.length === 0;

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="font-heading text-xl font-semibold">Investigation Workspace</h1>
        <p className="text-muted-foreground text-sm">
          Your case queue — select a case to open it as a tab below.
        </p>
        {deepLinkError && (
          <p className="text-destructive mt-1 text-xs" role="alert">
            Couldn&apos;t open the linked case: {deepLinkError}
          </p>
        )}
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        <div className={cn("flex shrink-0 flex-col gap-2", collapsed ? "w-auto" : "w-full lg:w-80")}>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => setCollapsed((c) => !c)}
              title={collapsed ? "Expand panel" : "Collapse panel"}
              aria-label={collapsed ? "Expand panel" : "Collapse panel"}
            >
              {collapsed ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
            </Button>
            {collapsed && openTabIds.length > 0 && (
              <Badge variant="outline" className="text-[10px]">
                {openTabIds.length}
              </Badge>
            )}
          </div>

          {collapsed ? (
            <Button
              variant={centerView === "queue" ? "secondary" : "ghost"}
              size="icon-sm"
              onClick={showQueue}
              title="Queue"
              aria-label="Queue"
            >
              <Inbox className="size-4" />
            </Button>
          ) : (
            <div className="rounded-xl border">
              <button
                type="button"
                onClick={showQueue}
                className={cn(
                  "flex w-full items-center gap-2 border-b px-3 py-2 text-sm font-medium",
                  centerView === "queue" ? "bg-muted/60" : "hover:bg-muted/40",
                )}
              >
                <Inbox className="size-4" />
                Queue
                <Badge variant="outline" className="ml-auto text-[10px]">
                  {initialQueue.total_count}
                </Badge>
              </button>
              <p className="text-muted-foreground border-b px-3 py-2 text-xs font-medium tracking-wide uppercase">
                Open Cases
              </p>
              <CaseTabBar />
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1 rounded-xl border">
          {/* Both the queue and every open tab stay permanently mounted —
              only CSS visibility toggles (`hidden`/undefined), never a
              conditional-mount ternary. A ternary here would unmount every
              open case tab's whole component tree (graph filters,
              transaction explorer pagination, notes draft render state,
              decision-panel local state, ...) each time the user switches to
              Queue and back — the exact keep-alive violation this codebase
              already found and fixed twice before, one level up
              (`case-tab-bar.tsx`'s tabs) and one level down (`case-tab-
              content.tsx`'s Triage/Deep toggle). `CaseTabContentWrapper`
              itself already does this correctly for the tab-vs-tab case;
              this is the same pattern applied to queue-vs-tabs. */}
          <div className={showQueueInCenter ? undefined : "hidden"}>
            <div className="flex flex-col gap-3 p-4">
              <h2 className="font-heading text-base font-semibold">Your Cases</h2>
              <CaseQueue initialData={initialQueue} />
            </div>
          </div>
          <div className={showQueueInCenter ? "hidden" : undefined}>
            {openTabIds.map((caseId) => (
              <CaseTabContentWrapper key={caseId} caseId={caseId} />
            ))}
          </div>
        </div>
      </div>

      <AiWidget />
    </div>
  );
}

// All `openTabIds` are rendered as siblings here, always mounted — this
// wrapper is the actual keep-alive visibility toggle (CSS `hidden`/`block`
// only, never `{activeTabId === id && <Tab/>}`, which would unmount the
// inactive tab and lose its scroll position / draft state). Visible only
// when it's both the active tab AND the center panel is actually showing
// tabs (not the queue) — kept alive underneath the queue view either way.
function CaseTabContentWrapper({ caseId }: { caseId: string }) {
  const activeTabId = useCaseTabStore((state) => state.activeTabId);
  const centerView = useCaseTabStore((state) => state.centerView);
  const visible = activeTabId === caseId && centerView === "tabs";
  return (
    <div className={visible ? "block" : "hidden"}>
      <CaseTabContent caseId={caseId} />
    </div>
  );
}
