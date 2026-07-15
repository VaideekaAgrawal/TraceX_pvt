/**
 * Shared error-to-HTTP-response mapping for BFF Route Handlers under
 * `app/api/**` that call the real backend via `lib/api/*-client.ts`
 * (`alerts-client.ts`, `audit-client.ts`, `dashboard-client.ts`). Every one
 * of those clients throws `BackendUnavailableError` for a genuine backend
 * fault and `BackendApiError` (with the backend's real status + detail
 * preserved) for a real rejection — see `response-mapping.ts` for that
 * triage. This module is the next layer up: turning those two thrown
 * types into the actual `NextResponse` the browser gets back.
 *
 * Extracted after the identical `try { ... } catch { ... }` block was
 * copy-pasted verbatim across 5 Route Handlers (`alerts/route.ts`,
 * `alerts/[alertId]/assign/route.ts`, `alerts/workload/route.ts`,
 * `audit-log/route.ts`, `dashboard/summary/route.ts`). That duplication is
 * exactly the bug class this same diff already got burned by once, live,
 * during its own verification pass: a legitimate 403 from `GET
 * /audit-log` was mis-mapped to a generic 502 in one of these copies
 * before the underlying triage was centralized (commit `a3f7d18f`).
 * Duplicating the *next* layer's mapping 5x left the next new BFF route
 * one paste-and-forget away from reintroducing that same bug
 * independently — hence one shared function here instead.
 *
 * Deliberately NOT used by `auth/login/route.ts`: that route's mapping is
 * not the same shape (it forces a fixed 401 for any backend 4xx rather
 * than forwarding the real status, specifically to avoid leaking a
 * credential-failure-mode signal, and always maps unreachability to 502
 * rather than rethrowing) — a real behavioral difference, not
 * boilerplate, so it stays as its own inline block.
 */
import { NextResponse } from "next/server";

import { BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";

/**
 * Runs `handler`, forwarding whatever `NextResponse` it returns unchanged.
 * If `handler` throws `BackendUnavailableError` -> 502. If it throws
 * `BackendApiError` -> the backend's own status + detail message,
 * forwarded as-is (this is what fixed the 403-mis-mapped-to-502 bug).
 * Anything else rethrows, so an unexpected bug here isn't silently turned
 * into a clean-looking JSON error response.
 */
export async function withBackendErrorMapping(
  handler: () => Promise<NextResponse>,
): Promise<NextResponse> {
  try {
    return await handler();
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      return NextResponse.json({ detail: err.message }, { status: 502 });
    }
    if (err instanceof BackendApiError) {
      return NextResponse.json({ detail: err.message }, { status: err.status });
    }
    throw err;
  }
}
