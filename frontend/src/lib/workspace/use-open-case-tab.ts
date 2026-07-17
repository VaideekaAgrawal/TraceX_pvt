"use client";

import { useState } from "react";

import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import type { CaseListItem } from "@/lib/api/types";

/**
 * Shared "open an arbitrary case referenced by a panel as a real tab" flow
 * — `GET /api/cases/{case_id}` (any case, per the backend's
 * `require_case_read_access`) + `useCaseTabStore`'s `openCase`. Used by
 * every panel that surfaces another case's id as a clickable reference
 * (`similar-cases.tsx`, `previous-alerts.tsx`) — previously each
 * implemented this fetch/loading/error flow independently; extracted here
 * so the two copies can't drift.
 */
export function useOpenCaseTab() {
  const openCase = useCaseTabStore((state) => state.openCase);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  async function handleOpen(targetCaseId: string) {
    setOpenError(null);
    setOpeningId(targetCaseId);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(targetCaseId)}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to open case");
      }
      openCase(body as CaseListItem);
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : "Failed to open case");
    } finally {
      setOpeningId(null);
    }
  }

  return { openingId, openError, handleOpen };
}
