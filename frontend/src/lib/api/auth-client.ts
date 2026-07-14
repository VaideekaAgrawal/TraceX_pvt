/**
 * Typed wrapper around the two backend routes this phase needs:
 * `POST /auth/login`, `GET /auth/me` (`backend/api/routes/auth.py`).
 * Server-only — called from the Next.js `/api/auth/login` Route Handler
 * and the root layout, never directly from a Client Component (the backend
 * has no CORS config, so a direct browser call would fail anyway; the BFF
 * pattern is not optional here).
 */
import "server-only";

import { authedBackendFetch, backendFetch, BackendApiError } from "@/lib/api/backend";
import type { BackendLoginResponse, CurrentUser, LoginRequest } from "@/lib/api/types";

const GENERIC_LOGIN_ERROR = "Invalid username or password";

/**
 * Thrown by `getCurrentUser()` when the backend itself is the problem
 * (network failure, 5xx, or a malformed 200 body) rather than the session
 * being invalid. Callers must NOT treat this the same as "not
 * authenticated" — a 5xx from `/auth/me` says nothing about whether the
 * token is still valid, so routing it through the logout/session-expired
 * path would destroy a perfectly good session. Callers should catch this
 * specifically and render a "service unavailable" state instead.
 */
export class BackendUnavailableError extends Error {
  constructor(message = "Unable to reach the authentication service") {
    super(message);
    this.name = "BackendUnavailableError";
  }
}

/**
 * Calls the real `POST /auth/login`. Throws `BackendApiError` on any
 * non-2xx response — the backend always returns the same generic message
 * for every failure mode (unknown user, wrong password, deactivated
 * account), so this doesn't try to distinguish them either.
 */
export async function loginAgainstBackend(
  body: LoginRequest,
): Promise<BackendLoginResponse> {
  const response = await backendFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new BackendApiError(GENERIC_LOGIN_ERROR, response.status);
  }

  return (await response.json()) as BackendLoginResponse;
}

/**
 * Calls `GET /auth/me` using the session cookie already on the incoming
 * request. Returns `null` for "not logged in" (no cookie) or "session
 * invalid/expired" (backend 401/403) — both are genuinely "render as
 * logged out". Throws `BackendUnavailableError` for anything that isn't a
 * statement about the session's validity (network failure, backend 5xx, or
 * a malformed 200 body) — see that class's docstring for why callers must
 * not conflate the two.
 */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  let response: Response | null;
  try {
    response = await authedBackendFetch("/auth/me");
  } catch {
    // Network-level failure (backend unreachable, DNS, timeout, etc.).
    throw new BackendUnavailableError();
  }

  if (response === null) {
    // No session cookie at all — genuinely not authenticated.
    return null;
  }

  if (response.status === 401 || response.status === 403) {
    // Backend explicitly rejected the token — genuinely not authenticated.
    return null;
  }

  if (!response.ok) {
    // Any other non-2xx (5xx etc.) is a backend fault, not proof the
    // session is invalid.
    throw new BackendUnavailableError();
  }

  try {
    return (await response.json()) as CurrentUser;
  } catch {
    // Malformed 200 body — also a backend fault, not an auth decision.
    throw new BackendUnavailableError();
  }
}
