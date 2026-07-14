/**
 * Typed wrapper around `backend/api/routes/dashboard.py`'s
 * `GET /dashboard/summary` (ROADMAP Phase 14). Server-only — called from
 * the Dashboard Server Component (first paint) and the
 * `/api/dashboard/summary` Route Handler (client-side refresh after a
 * successful assign), never directly from a Client Component.
 */
import "server-only";

import { authedBackendFetch } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import type { DashboardSummaryResponse } from "@/lib/api/types";

/**
 * `GET /dashboard/summary` — identical response for both roles (no RBAC
 * beyond plain authentication, per that route's docstring). Returns `null`
 * for "not authenticated" (no cookie, or backend 401); throws
 * `BackendUnavailableError` for a real backend fault.
 */
export async function getDashboardSummary(): Promise<DashboardSummaryResponse | null> {
  let response: Response | null;
  try {
    response = await authedBackendFetch("/dashboard/summary");
  } catch {
    throw new BackendUnavailableError("Unable to reach the dashboard service");
  }

  if (response === null) return null;
  if (response.status === 401) return null;
  if (!response.ok) throw new BackendUnavailableError("Unable to reach the dashboard service");

  try {
    return (await response.json()) as DashboardSummaryResponse;
  } catch {
    throw new BackendUnavailableError("Unable to reach the dashboard service");
  }
}
