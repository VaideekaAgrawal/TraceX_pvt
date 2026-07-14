/**
 * Shared response triage for the read-side server-only clients
 * (`alerts-client.ts`'s `listAlerts`/`getWorkload`, `audit-client.ts`'s
 * `listAuditLog`, `dashboard-client.ts`'s `getDashboardSummary`) — all of
 * them are simple GETs behind either `get_current_user` or `require_role`.
 *
 * Found live during this phase's verification pass, not in review: a 403
 * from `GET /audit-log` (an Investigator explicitly requesting another
 * actor's `actor_id`, which the backend correctly rejects per that
 * route's RBAC data-scoping) was originally mapped to a generic 502
 * "service unavailable" instead of forwarded as a real 403 — because the
 * naive version of these functions only special-cased 401 and threw
 * `BackendUnavailableError` for every other non-2xx, conflating "the
 * backend told me no" with "the backend is broken." Centralizing the
 * triage here means that class of bug can't recur independently per
 * client file.
 *
 * Triage:
 *   - no cookie, or 401 -> `null` ("not authenticated", a valid outcome
 *     for these routes — callers render as logged out).
 *   - any other 4xx (403 forbidden, 400/422 validation) -> throws
 *     `BackendApiError` with the real status + backend detail, so the
 *     calling Route Handler forwards it as-is instead of masking it.
 *   - 5xx, or a malformed 200 body -> throws `BackendUnavailableError`
 *     (a genuine backend fault, not a statement about the request itself).
 */
import "server-only";

import { BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export async function parseAuthedJsonResponse<T>(
  response: Response | null,
  unavailableMessage: string,
): Promise<T | null> {
  if (response === null) return null;
  if (response.status === 401) return null;

  if (!response.ok) {
    if (response.status >= 500) {
      throw new BackendUnavailableError(unavailableMessage);
    }
    const detail = await readErrorDetail(response);
    throw new BackendApiError(detail, response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new BackendUnavailableError(unavailableMessage);
  }
}
