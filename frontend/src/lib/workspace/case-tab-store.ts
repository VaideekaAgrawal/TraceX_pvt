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

import type { CaseListItem } from "@/lib/api/types";

export interface CaseTabState {
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
   * If `case_id` is already an open tab, just activates it — never
   * duplicates a tab for a case already open. If it was previously opened
   * and then closed (its `tabState` entry still exists — `closeTab` never
   * deletes it), reopens it with that same draft/scroll/filter state
   * intact, refreshing only the cached `summary` fields. Otherwise
   * initializes a brand-new `tabState` entry with the documented defaults.
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
  setActiveTab: (caseId: string) => void;
  updateTabState: (caseId: string, patch: Partial<CaseTabState>) => void;
}

function defaultTabState(item: CaseListItem): CaseTabState {
  return {
    activeView: "triage",
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

  openCase: (item) =>
    set((state) => {
      if (state.openTabIds.includes(item.case_id)) {
        return { activeTabId: item.case_id };
      }

      const existing = state.tabState[item.case_id];
      return {
        openTabIds: [...state.openTabIds, item.case_id],
        activeTabId: item.case_id,
        tabState: {
          ...state.tabState,
          [item.case_id]: existing ? { ...existing, summary: item } : defaultTabState(item),
        },
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
    set((state) => (state.openTabIds.includes(caseId) ? { activeTabId: caseId } : state)),

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
