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
 * invalid/expired" (backend 401) — both are the same "render as logged
 * out" case for the root layout, which is the only caller today.
 */
export async function getCurrentUser(): Promise<CurrentUser | null> {
  const response = await authedBackendFetch("/auth/me");
  if (response === null) {
    return null;
  }
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as CurrentUser;
}
