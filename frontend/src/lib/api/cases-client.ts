/**
 * Typed wrapper around `backend/api/routes/cases.py`'s `GET /cases`
 * (ROADMAP Phase 15). Server-only — called from this app's own
 * `/api/cases` Route Handler and from `workspace/page.tsx`'s first-paint
 * fetch, never directly from a Client Component (see `lib/api/backend.ts`'s
 * docstring on why the BFF pattern isn't optional here). Mirrors
 * `alerts-client.ts::listAlerts`'s exact convention.
 */
import "server-only";

import { authedBackendFetch } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { parseAuthedJsonResponse } from "@/lib/api/response-mapping";
import type { CaseListParams, CaseListResponse } from "@/lib/api/types";

function toQueryString(params: Record<string, unknown>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    qs.set(key, String(value));
  }
  return qs.toString();
}

/**
 * Role-scoped case list — `INVESTIGATOR` sees `assigned_to = me`,
 * `ADMIN_COMPLIANCE` sees their `AWAITING_REVIEW`/`ESCALATED` review queue
 * (entirely server-side scoping, per that route's docstring — this
 * function doesn't replicate the logic, just calls the endpoint). Returns
 * `null` for "not authenticated" (no session cookie, or the backend
 * rejected the token with 401). Throws `BackendApiError` for a real
 * rejection (e.g. an Admin supplying a `status` outside their allowed set
 * -> backend 400) with the real status preserved, or
 * `BackendUnavailableError` for a genuine backend fault (5xx) — see
 * `response-mapping.ts`.
 */
export async function listCases(
  params: CaseListParams = {},
): Promise<CaseListResponse | null> {
  const qs = toQueryString(params as Record<string, unknown>);

  let response: Response | null;
  try {
    response = await authedBackendFetch(`/cases${qs ? `?${qs}` : ""}`);
  } catch {
    throw new BackendUnavailableError("Unable to reach the cases service");
  }

  return parseAuthedJsonResponse<CaseListResponse>(response, "Unable to reach the cases service");
}
