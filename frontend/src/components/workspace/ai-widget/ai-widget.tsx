"use client";

import { useCallback, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { Sparkles, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { CopilotPanel } from "@/components/workspace/ai-widget/copilot-panel";
import { RecommendationsPanel } from "@/components/workspace/ai-widget/recommendations-panel";
import { useAuth, useRole } from "@/lib/auth/auth-provider";
import { isAssignedToUser } from "@/lib/workspace/case-assignment";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";

// A pointer movement under this many pixels (either axis) between
// pointerdown and pointerup counts as "didn't really drag" — i.e. a click,
// which expands the widget. Anything past it is treated as a genuine drag
// and does NOT expand on release (so dragging the FAB never accidentally
// also opens the panel).
const CLICK_DRAG_THRESHOLD_PX = 5;

/**
 * Floating AI widget — mounted once, globally, in `workspace-shell.tsx`
 * (ROADMAP Phase 19, previously blocked on backend Phase 9, now unblocked).
 * Two states:
 *
 *   - Collapsed: a circular floating action button, `fixed` positioned
 *     bottom-right with a high `z-index` so it sits on top of every panel.
 *     Draggable via plain pointer events (`onPointerDown`/`onPointerMove`/
 *     `onPointerUp` + `setPointerCapture`, no drag library) — session-local
 *     `{x, y}` offset state only, no persistence across reload (this is a
 *     convenience affordance, not saved layout). A `pointerup` with total
 *     movement under `CLICK_DRAG_THRESHOLD_PX` on both axes is treated as a
 *     real click and expands the widget instead.
 *   - Expanded: a fixed-position rectangular chat-style panel, always
 *     anchored bottom-right regardless of wherever the FAB was last dragged
 *     to (a deliberate simplicity call — re-anchoring the expanded panel to
 *     track an arbitrary dragged FAB position risks it landing partway off
 *     -screen; a full-size panel losing exact positional continuity with a
 *     40px button on expand is a minor, forgivable discontinuity, not a
 *     confusing one). Contains two sections, "Recommendations" (case-
 *     scoped, wired to `backend/api/routes/recommendations.py`) and
 *     "Copilot" (cross-case, wired to `backend/api/routes/copilot.py`,
 *     see `copilot-panel.tsx` — real as of ROADMAP Phase 20, previously
 *     an honest "coming soon" placeholder while Backend Phase 10 didn't
 *     exist).
 *
 * Case scoping: reads `activeTabId`/`centerView`/`openTabIds`/`tabState`
 * directly off the shared Zustand tab store — the same store every case tab
 * uses — so it always knows which case (if any) is "current" regardless of
 * whether the center panel is showing that case's tab or the queue. Scoped
 * to `null` (no case) whenever the center panel is on the queue view or no
 * tabs are open at all — matches `workspace-shell.tsx`'s own
 * `showQueueInCenter` derivation, not a separate one.
 */
export function AiWidget() {
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<"recommendations" | "copilot">("recommendations");
  const [offset, setOffset] = useState({ x: 0, y: 0 });

  const dragRef = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);

  const activeTabId = useCaseTabStore((state) => state.activeTabId);
  const centerView = useCaseTabStore((state) => state.centerView);
  const openTabIds = useCaseTabStore((state) => state.openTabIds);
  const tabState = useCaseTabStore((state) => state.tabState);

  const scopedCaseId =
    centerView === "tabs" && openTabIds.length > 0 && activeTabId ? activeTabId : null;
  const summary = scopedCaseId ? (tabState[scopedCaseId]?.summary ?? null) : null;

  const role = useRole();
  const isAdmin = role === "ADMIN_COMPLIANCE";
  const { user } = useAuth();
  // Same shared `isAssignedToUser` check `decision-panel.tsx` uses for its
  // own read-only gating — both `/recommendations` and `/recommendations/
  // challenge` are assignment-gated (`require_case_access`), not the
  // read-only dependency every other L1/L2 GET uses.
  const canAct = scopedCaseId != null && (isAdmin || isAssignedToUser(summary, user?.user_id));

  const handlePointerDown = useCallback(
    (e: ReactPointerEvent<HTMLButtonElement>) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      dragRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        originX: offset.x,
        originY: offset.y,
        moved: false,
      };
    },
    [offset],
  );

  const handlePointerMove = useCallback((e: ReactPointerEvent<HTMLButtonElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    if (Math.abs(dx) > CLICK_DRAG_THRESHOLD_PX || Math.abs(dy) > CLICK_DRAG_THRESHOLD_PX) {
      drag.moved = true;
    }
    setOffset({ x: drag.originX + dx, y: drag.originY + dy });
  }, []);

  const handlePointerUp = useCallback(() => {
    const wasDrag = dragRef.current?.moved ?? false;
    dragRef.current = null;
    if (!wasDrag) {
      setExpanded(true);
    }
  }, []);

  if (!expanded) {
    return (
      <button
        type="button"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        aria-label="Open AI assistant"
        title="AI assistant — drag to move, click to open"
        style={{ transform: `translate(${offset.x}px, ${offset.y}px)` }}
        className="fixed right-6 bottom-6 z-50 flex size-14 touch-none items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-shadow hover:shadow-xl"
      >
        <Sparkles className="size-6" />
      </button>
    );
  }

  return (
    <div className="fixed right-6 bottom-6 z-50 flex h-[560px] w-[400px] flex-col overflow-hidden rounded-xl border bg-background shadow-2xl">
      <div className="flex items-center gap-2 border-b p-3">
        <Sparkles className="size-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">AI Assistant</p>
          <p className="text-muted-foreground truncate text-xs">
            {scopedCaseId ? `Scoped to ${scopedCaseId}` : "No case open — open a case to see recommendations"}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={() => setExpanded(false)}
          aria-label="Collapse AI assistant"
        >
          <X className="size-4" />
        </Button>
      </div>

      <div className="flex items-center gap-1 border-b p-2">
        <Button
          variant={tab === "recommendations" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("recommendations")}
        >
          Recommendations
        </Button>
        <Button
          variant={tab === "copilot" ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTab("copilot")}
        >
          Copilot
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tab === "recommendations" ? (
          <RecommendationsPanel caseId={scopedCaseId} canAct={canAct} />
        ) : (
          <CopilotPanel />
        )}
      </div>
    </div>
  );
}
