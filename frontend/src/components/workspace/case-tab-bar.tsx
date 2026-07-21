"use client";

import { X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { getCaseStageLabel } from "@/lib/workspace/case-stage";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";

/**
 * Hand-built tab bar — deliberately NOT shadcn `tabs`/Radix `Tabs`
 * (`@base-ui/react`'s `Tabs.Panel` unmounts inactive content by default,
 * which would break the keep-alive requirement `workspace-shell.tsx`
 * implements). A plain button-per-tab bar with a "×" close control avoids
 * fighting that library's default behavior.
 *
 * Vertical rail, not a horizontal strip — `workspace-shell.tsx` places this
 * beside the queue in a left column, tabs reading top-to-bottom, so it
 * reads as a case list rather than a browser-style tab strip; no
 * rounded-top/no-bottom-border "physically attached to the content below
 * it" styling either, since that doesn't make sense once the content is
 * beside it, not below it.
 *
 * ROADMAP Phase 22 a11y fix: each tab is a real `<button aria-pressed>`
 * (native focus/Enter/Space handling, no manual `tabIndex`/`onKeyDown`
 * needed), not a `role="tab"` element. `role="tablist"`/`role="tab"` was
 * tried first but doesn't fit this widget: ARIA's "required owned elements"
 * check requires a `tablist`'s children to be *only* `tab`-role elements,
 * which this bar's per-row close button structurally can't satisfy no
 * matter how it's wrapped (a `role="presentation"` wrapper gets "flattened"
 * for that check, which promotes the close button too, not just the tab —
 * axe still flags it as an unallowed tablist child). `aria-pressed` on a
 * plain button conveys the same "this one is currently selected" state
 * without that structural requirement, and the close button is a normal
 * sibling.
 *
 * No "+" button: new tabs only ever come from clicking a queue row
 * (`case-queue.tsx`) or the Dashboard `?case=` deep link — there is no
 * "create a blank case" flow anywhere in this system, so a bare "+" has
 * nothing well-defined to do. This is a deliberate deviation from the
 * literal `Case 102 | Case 245 | +` mockup in `FRONTEND_PLAN.md` §3.1.
 */
export function CaseTabBar() {
  const openTabIds = useCaseTabStore((state) => state.openTabIds);
  const activeTabId = useCaseTabStore((state) => state.activeTabId);
  const tabState = useCaseTabStore((state) => state.tabState);
  const setActiveTab = useCaseTabStore((state) => state.setActiveTab);
  const closeTab = useCaseTabStore((state) => state.closeTab);

  if (openTabIds.length === 0) {
    return (
      <p className="text-muted-foreground px-3 py-2 text-sm">
        No cases open — select a case from the queue to open it here.
      </p>
    );
  }

  return (
    <div role="group" aria-label="Open cases" className="flex flex-col gap-1 p-2">
      {openTabIds.map((caseId) => {
        const state = tabState[caseId];
        const active = activeTabId === caseId;
        return (
          <div
            key={caseId}
            className={cn(
              "flex w-full items-center gap-2 rounded-lg border px-3 py-1.5 text-sm",
              active
                ? "bg-background font-medium"
                : "bg-muted/40 text-muted-foreground hover:bg-muted/70",
            )}
          >
            <button
              type="button"
              aria-pressed={active}
              onClick={() => setActiveTab(caseId)}
              className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left"
            >
              <span className="min-w-0 flex-1 truncate">{caseId}</span>
              {state && (
                <Badge variant="outline" className="text-[10px]">
                  {getCaseStageLabel(state.summary.status)}
                </Badge>
              )}
            </button>
            <button
              type="button"
              aria-label={`Close ${caseId} tab`}
              className="hover:bg-muted shrink-0 rounded p-0.5"
              onClick={() => closeTab(caseId)}
            >
              <X className="size-3" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
