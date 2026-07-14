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
import { parseAuthedJsonResponse } from "@/lib/api/response-mapping";
import type { DashboardSummaryResponse } from "@/lib/api/types";

/**
 * `GET /dashboard/summary` — identical response for both roles (no RBAC
 * beyond plain authentication, per that route's docstring). Returns `null`
 * for "not authenticated" (no cookie, or backend 401); throws
 * `BackendApiError` for any other real rejection, `BackendUnavailableError`
 * for a genuine backend fault (5xx) — see `response-mapping.ts`.
 */
export async function getDashboardSummary(): Promise<DashboardSummaryResponse | null> {
  let response: Response | null;
  try {
    response = await authedBackendFetch("/dashboard/summary");
  } catch {
    throw new BackendUnavailableError("Unable to reach the dashboard service");
  }

  return parseAuthedJsonResponse<DashboardSummaryResponse>(
    response,
    "Unable to reach the dashboard service",
  );
}
