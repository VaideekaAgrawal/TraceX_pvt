"use client";

/**
 * Per-case-tab client state for the Investigation Workspace
 * (`docs/FRONTEND_ROADMAP.md` Phase 15 / `FRONTEND_PLAN.md` §3.1). The
 * first Zustand store in this repo — deliberately not React Context, since
 * this is genuinely per-`case_id`-keyed state, unlike auth's single global
 * value (see `lib/auth/auth-provider.tsx`'s docstring for that contrast).
 *
 * Both entry points that open a case tab — the queue list
 * (`case-queue.tsx`) and the Dashboard `?case=` deep link, resolved by
 * `workspace-shell.tsx` — call `openCase` on this same store. That
 * convergence (not two separate "open a tab" implementations) is an
 * explicit Phase 15 requirement.
 *
 * Nothing here is persisted across a browser refresh (explicitly deferred
 * per the roadmap — a possible later enhancement, not built speculatively).
 */
import { create } from "zustand";

import { getDefaultActiveView } from "@/lib/workspace/case-stage";
import type { CaseListItem } from "@/lib/api/types";

export interface CaseTabState {
  // Defaulted from the case's own status (`getDefaultActiveView`, ROADMAP
  // Phase 17) whenever a genuinely new tab opens, or an already-open tab's
  // cached `summary.status` changes (see `openCase` below) — freely
  // switchable afterward via `case-tab-content.tsx`'s view toggle, this is
  // only ever the *default*.
  activeView: "triage" | "deep";
  scrollOffset: number;
  graphFilters: Record<string, unknown>;
  graphExpandState: Record<string, unknown>;
  notesDraft: string;
  similarCasesExpanded: boolean;
  // Cached queue-list fields (`status`/`priority`/`primary_account_id`,
  // plus the rest of `CaseListItem`) so the tab bar/body can render basic
  // info without a second fetch — refreshed whenever `openCase` is called
  // again for an already-open-or-previously-open tab (see `openCase`
  // below), otherwise left as whatever it was seeded with.
  summary: CaseListItem;
}

interface CaseTabStore {
  openTabIds: string[];
  activeTabId: string | null;
  tabState: Record<string, CaseTabState>;
  /**
   * Which content the center panel shows — `"queue"` (the full case queue
   * table) or `"tabs"` (the active tab's `CaseTabContent`). Defaults to
   * `"queue"`: the queue table used to sit permanently in the left column;
   * it's now a center-panel view you navigate to, same as any case tab, via
   * the left panel's "Queue" nav entry (`showQueue`) or by opening/focusing
   * a case (`openCase`/`setActiveTab`, both of which flip this to `"tabs"`).
   * Switching to `"queue"` never touches `openTabIds`/`activeTabId`/
   * `tabState` — any open tabs stay open in the background, ready to resume
   * exactly where they were left.
   */
  centerView: "queue" | "tabs";
  /**
   * If `case_id` is already an open tab, just activates it — never
   * duplicates a tab for a case already open. If it was previously opened
   * and then closed (its `tabState` entry still exists — `closeTab` never
   * deletes it), reopens it with that same draft/scroll/filter state
   * intact, refreshing only the cached `summary` fields. Otherwise
   * initializes a brand-new `tabState` entry with the documented defaults.
   * Always also sets `centerView: "tabs"` — opening/focusing a case should
   * switch the center panel to show it.
   */
  openCase: (item: CaseListItem) => void;
  /**
   * Removes `case_id` from `openTabIds` only — the case itself isn't
   * "closed" (it stays in the queue list either way), and its `tabState`
   * entry is deliberately kept so a later `openCase` reopens with the same
   * draft/scroll state rather than resetting it. If the closed tab was
   * active, activates the tab that was immediately to its left; if it was
   * the leftmost tab, activates the tab that's now leftmost instead (i.e.
   * the one that was immediately to its right); `null` if no tabs remain.
   */
  closeTab: (caseId: string) => void;
  /** Also sets `centerView: "tabs"` — clicking an already-open tab in the
   * rail should switch away from the queue view back to that tab's content. */
  setActiveTab: (caseId: string) => void;
  /** Switches the center panel to the queue table. Does NOT touch
   * `openTabIds`/`activeTabId`/`tabState` — open tabs stay open in the
   * background. */
  showQueue: () => void;
  updateTabState: (caseId: string, patch: Partial<CaseTabState>) => void;
}

function defaultTabState(item: CaseListItem): CaseTabState {
  return {
    activeView: getDefaultActiveView(item.status),
    scrollOffset: 0,
    graphFilters: {},
    graphExpandState: {},
    notesDraft: "",
    similarCasesExpanded: false,
    summary: item,
  };
}

export const useCaseTabStore = create<CaseTabStore>((set) => ({
  openTabIds: [],
  activeTabId: null,
  tabState: {},
  centerView: "queue",

  openCase: (item) =>
    set((state) => {
      const existing = state.tabState[item.case_id];
      // Recompute the default view only when the case's status actually
      // changed since it was last cached here (a real server-side
      // transition, e.g. someone escalated it) — not on every re-open of an
      // already-current tab, which would otherwise clobber a manual
      // triage<->deep toggle every time the investigator just refocuses the
      // tab from the queue (ROADMAP Phase 17 judgment call, documented in
      // `case-stage.ts`'s `getDefaultActiveView` docstring).
      const statusChanged = existing != null && existing.summary.status !== item.status;
      const nextTabState = {
        ...state.tabState,
        [item.case_id]: existing
          ? {
              ...existing,
              summary: item,
              activeView: statusChanged ? getDefaultActiveView(item.status) : existing.activeView,
            }
          : defaultTabState(item),
      };

      if (state.openTabIds.includes(item.case_id)) {
        // Already open — just refresh the cached summary (e.g. the case's
        // status changed server-side since it was opened) and focus it,
        // rather than leaving stale fields displayed until a close/reopen.
        return { activeTabId: item.case_id, tabState: nextTabState, centerView: "tabs" };
      }

      return {
        openTabIds: [...state.openTabIds, item.case_id],
        activeTabId: item.case_id,
        tabState: nextTabState,
        centerView: "tabs",
      };
    }),

  closeTab: (caseId) =>
    set((state) => {
      const idx = state.openTabIds.indexOf(caseId);
      if (idx === -1) return state;

      const openTabIds = state.openTabIds.filter((id) => id !== caseId);
      let activeTabId = state.activeTabId;
      if (state.activeTabId === caseId) {
        activeTabId = idx > 0 ? state.openTabIds[idx - 1] : (openTabIds[0] ?? null);
      }

      // `tabState` is intentionally left untouched — see this action's
      // docstring on the store interface above.
      return { openTabIds, activeTabId };
    }),

  setActiveTab: (caseId) =>
    set((state) =>
      state.openTabIds.includes(caseId) ? { activeTabId: caseId, centerView: "tabs" } : state,
    ),

  showQueue: () => set({ centerView: "queue" }),

  updateTabState: (caseId, patch) =>
    set((state) => {
      const existing = state.tabState[caseId];
      if (!existing) return state;
      return {
        tabState: {
          ...state.tabState,
          [caseId]: { ...existing, ...patch },
        },
      };
    }),
}));
