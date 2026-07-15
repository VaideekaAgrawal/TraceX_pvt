/**
 * Typed wrapper around `backend/api/routes/alerts.py`'s three routes:
 * `GET /alerts`, `GET /alerts/workload`, `PATCH /alerts/{alert_id}/assign`
 * (ROADMAP Phase 14). Server-only — called from this app's own
 * `/api/alerts*` Route Handlers, never directly from a Client Component
 * (see `lib/api/backend.ts`'s docstring on why the BFF pattern isn't
 * optional here).
 */
import "server-only";

import { authedBackendFetch, BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { parseAuthedJsonResponse } from "@/lib/api/response-mapping";
import type {
  AlertListParams,
  AlertListResponse,
  AssignAlertResponse,
  WorkloadResponse,
} from "@/lib/api/types";

function toQueryString(params: Record<string, unknown>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) qs.append(key, String(item));
    } else {
      qs.set(key, String(value));
    }
  }
  return qs.toString();
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

/**
 * System-wide, paginated alert list — identical response for both roles
 * (locked roadmap decision; the route itself has no role gate beyond plain
 * authentication). Returns `null` for "not authenticated" (no session
 * cookie, or the backend rejected the token with 401). Throws
 * `BackendApiError` for a real rejection (e.g. an invalid `sort` value ->
 * backend 400) with the real status preserved, or `BackendUnavailableError`
 * for a genuine backend fault (5xx) — see `response-mapping.ts` for why
 * these must not be conflated (a live-verification-caught bug in this
 * phase's earlier draft did exactly that for `listAuditLog`).
 */
export async function listAlerts(
  params: AlertListParams = {},
): Promise<AlertListResponse | null> {
  const qs = toQueryString(params as Record<string, unknown>);

  let response: Response | null;
  try {
    response = await authedBackendFetch(`/alerts${qs ? `?${qs}` : ""}`);
  } catch {
    throw new BackendUnavailableError("Unable to reach the alerts service");
  }

  return parseAuthedJsonResponse<AlertListResponse>(response, "Unable to reach the alerts service");
}

/**
 * Per-investigator open-case counts, Admin/Compliance only
 * (`require_role(ADMIN_COMPLIANCE)` on the backend route). Returns `null`
 * only for "genuinely not authenticated" (no cookie, or backend 401) —
 * unlike that, a 403 here is a real authorization failure (an
 * authenticated Investigator hitting an Admin-only route), not "not
 * logged in", so `parseAuthedJsonResponse` throws `BackendApiError` for
 * it instead of folding it into the `null` case — the calling Route
 * Handler forwards the 403 rather than silently returning empty data.
 */
export async function getWorkload(): Promise<WorkloadResponse | null> {
  let response: Response | null;
  try {
    response = await authedBackendFetch("/alerts/workload");
  } catch {
    throw new BackendUnavailableError("Unable to reach the alerts service");
  }

  return parseAuthedJsonResponse<WorkloadResponse>(response, "Unable to reach the alerts service");
}

/**
 * Manual (re)assignment of the case behind `alertId`, Admin/Compliance
 * only. Always throws on non-2xx (including "not authenticated" — there is
 * no sensible `null` return for a write) so the calling Route Handler maps
 * the failure to a real HTTP status for the browser.
 */
export async function assignAlert(
  alertId: string,
  investigatorId: string,
): Promise<AssignAlertResponse> {
  let response: Response | null;
  try {
    response = await authedBackendFetch(`/alerts/${encodeURIComponent(alertId)}/assign`, {
      method: "PATCH",
      body: JSON.stringify({ investigator_id: investigatorId }),
    });
  } catch {
    throw new BackendUnavailableError("Unable to reach the alerts service");
  }

  if (response === null) {
    throw new BackendApiError("Not authenticated", 401);
  }
  if (!response.ok) {
    const detail = await readErrorDetail(response, "Failed to assign alert");
    throw new BackendApiError(detail, response.status);
  }

  return (await response.json()) as AssignAlertResponse;
}
