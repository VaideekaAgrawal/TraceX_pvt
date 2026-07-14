/**
 * Server-only fetch helper for calling the real FastAPI backend
 * (`backend/api/app.py`). The backend has no CORS middleware configured,
 * so this must only ever run in Server Components / Route Handlers — never
 * imported by a Client Component.
 *
 * Base URL comes from `BACKEND_API_URL`, never hardcoded (see
 * `.env.example`).
 */
import "server-only";

import { cookies } from "next/headers";

import { SESSION_COOKIE_NAME } from "@/lib/auth/session";

export class BackendApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "BackendApiError";
  }
}

function backendBaseUrl(): string {
  const url = process.env.BACKEND_API_URL;
  if (!url) {
    throw new Error(
      "BACKEND_API_URL is not set — copy .env.example to .env.local and set it.",
    );
  }
  return url.replace(/\/$/, "");
}

/**
 * Low-level call, unauthenticated — used by the login Route Handler, which
 * doesn't have a session cookie yet (it's creating one).
 */
export async function backendFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = `${backendBaseUrl()}${path}`;
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
    // Every call here is request-scoped (auth state, case data) — never
    // cache across requests/users.
    cache: "no-store",
  });
  return response;
}

/**
 * Reads the session cookie (if present) and attaches it as a bearer token.
 * Returns `null` if there's no cookie at all — callers decide how to react
 * (e.g. the root layout treats that as "not logged in", not an error).
 */
export async function authedBackendFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response | null> {
  const cookieStore = await cookies();
  const token = cookieStore.get(SESSION_COOKIE_NAME)?.value;
  if (!token) {
    return null;
  }
  return backendFetch(path, {
    ...init,
    headers: {
      ...init.headers,
      Authorization: `Bearer ${token}`,
    },
  });
}
