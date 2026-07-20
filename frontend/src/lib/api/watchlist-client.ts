/**
 * Typed wrappers around `backend/api/routes/watchlist.py` — persistent
 * monitoring (ROADMAP Phase 11 backend / Phase 21 frontend, My Center →
 * Monitoring). Server-only — called from this app's own `/api/watchlist`
 * and `/api/watchlist/[entryId]` Route Handlers, never directly from a
 * Client Component. Mirrors `case-detail-client.ts`'s exact conventions.
 *
 * `removeWatchlistEntry` is this codebase's first client function wrapping
 * a `DELETE` backend route — see `app/api/watchlist/[entryId]/route.ts`
 * (the first BFF `DELETE` handler) for the other half of that "first."
 */
import "server-only";

import { authedBackendFetch, BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { parseAuthedJsonResponse } from "@/lib/api/response-mapping";
import type { AddWatchlistRequest, WatchlistEntryModel } from "@/lib/api/types";

const UNAVAILABLE = "Unable to reach the watchlist service";

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

/**
 * `GET /watchlist` — every active entry, enriched (display name / current
 * risk / latest activity / post-entry alert history). Open to any
 * authenticated user server-side (no role gate) — returns `null` only for
 * "not authenticated" (no session cookie, or backend 401).
 */
export async function listWatchlist(): Promise<WatchlistEntryModel[] | null> {
  let response: Response | null;
  try {
    response = await authedBackendFetch("/watchlist");
  } catch {
    throw new BackendUnavailableError(UNAVAILABLE);
  }
  return parseAuthedJsonResponse<WatchlistEntryModel[]>(response, UNAVAILABLE);
}

/**
 * `POST /watchlist` — Admin/Compliance only server-side (403 otherwise);
 * `monitoring-section.tsx` hides the add form for a non-admin. Idempotent
 * on (entity_type, entity_value) — re-adding an already-active entry
 * returns it rather than erroring, per the backend's own documented
 * behavior.
 */
export async function addWatchlistEntry(
  body: AddWatchlistRequest,
): Promise<WatchlistEntryModel> {
  let response: Response | null;
  try {
    response = await authedBackendFetch("/watchlist", {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch {
    throw new BackendUnavailableError(UNAVAILABLE);
  }
  if (response === null) {
    throw new BackendApiError("Not authenticated", 401);
  }
  if (!response.ok) {
    const detail = await readErrorDetail(response, "Failed to add watchlist entry");
    throw new BackendApiError(detail, response.status);
  }
  return (await response.json()) as WatchlistEntryModel;
}

/**
 * `DELETE /watchlist/{entry_id}` — soft-deletes (deactivates) an entry.
 * Admin/Compliance only server-side, same posture as `addWatchlistEntry`.
 * Always throws on non-2xx (including "not authenticated") — a `DELETE`
 * has no sensible silent-`null` return, same convention every write
 * function in this codebase's client layer already follows.
 */
export async function removeWatchlistEntry(entryId: string): Promise<void> {
  let response: Response | null;
  try {
    response = await authedBackendFetch(`/watchlist/${encodeURIComponent(entryId)}`, {
      method: "DELETE",
    });
  } catch {
    throw new BackendUnavailableError(UNAVAILABLE);
  }
  if (response === null) {
    throw new BackendApiError("Not authenticated", 401);
  }
  if (!response.ok) {
    const detail = await readErrorDetail(response, "Failed to remove watchlist entry");
    throw new BackendApiError(detail, response.status);
  }
  // 204 No Content — no body to parse.
}
