/**
 * Typed wrapper around `backend/api/routes/audit.py`'s `GET /audit-log`
 * (ROADMAP Phase 14). Server-only — called from this app's own
 * `/api/audit-log` Route Handler, never directly from a Client Component.
 * Backs both the Dashboard/My Center audit views and the notification
 * bell's curated `action` feed — one route, multiple consumers, per
 * `docs/FRONTEND_ROADMAP.md`'s Phase 14 scope.
 */
import "server-only";

import { authedBackendFetch } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { parseAuthedJsonResponse } from "@/lib/api/response-mapping";
import type { AuditLogListResponse, AuditLogParams } from "@/lib/api/types";

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

/**
 * `GET /audit-log`. The backend itself does the RBAC data-scoping
 * (Investigators are pinned to their own `actor_id` server-side,
 * Admin/Compliance sees everyone's) — this client passes whatever
 * `actor_id` it's given straight through and lets the backend enforce it,
 * matching the "backend is the real gate" invariant. Returns `null` for
 * "not authenticated" (no cookie, or backend 401); throws
 * `BackendApiError` for a real rejection (e.g. an Investigator explicitly
 * requesting another actor's `actor_id` -> backend 403 — must NOT be
 * mapped to a generic "service unavailable", see `response-mapping.ts`);
 * throws `BackendUnavailableError` for a genuine backend fault (5xx).
 */
export async function listAuditLog(
  params: AuditLogParams = {},
): Promise<AuditLogListResponse | null> {
  const qs = toQueryString(params as Record<string, unknown>);

  let response: Response | null;
  try {
    response = await authedBackendFetch(`/audit-log${qs ? `?${qs}` : ""}`);
  } catch {
    throw new BackendUnavailableError("Unable to reach the audit log service");
  }

  return parseAuthedJsonResponse<AuditLogListResponse>(
    response,
    "Unable to reach the audit log service",
  );
}
