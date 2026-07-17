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
 * reads as a case list rather than a browser-style tab strip. Same
 * close-button/active-state/keyboard-nav logic as before, just restacked
 * (`flex-col` instead of `flex-wrap`); no rounded-top/no-bottom-border
 * "physically attached to the content below it" styling either, since that
 * doesn't make sense once the content is beside it, not below it.
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
    <div className="flex flex-col gap-1 p-2">
      {openTabIds.map((caseId) => {
        const state = tabState[caseId];
        const active = activeTabId === caseId;
        return (
          <div
            key={caseId}
            role="tab"
            aria-selected={active}
            tabIndex={0}
            onClick={() => setActiveTab(caseId)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                setActiveTab(caseId);
              }
            }}
            className={cn(
              "flex w-full cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-sm",
              active
                ? "bg-background font-medium"
                : "bg-muted/40 text-muted-foreground hover:bg-muted/70",
            )}
          >
            <span className="min-w-0 flex-1 truncate">{caseId}</span>
            {state && (
              <Badge variant="outline" className="text-[10px]">
                {getCaseStageLabel(state.summary.status)}
              </Badge>
            )}
            <button
              type="button"
              aria-label={`Close ${caseId} tab`}
              className="hover:bg-muted shrink-0 rounded p-0.5"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(caseId);
              }}
            >
              <X className="size-3" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
