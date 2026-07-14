/**
 * BFF login endpoint: the browser POSTs credentials here (never directly to
 * the FastAPI backend — no CORS is configured there). This route calls the
 * real backend server-side, then sets the JWT it gets back as an httpOnly
 * cookie on the Next.js origin. Only non-sensitive fields (role, user_id)
 * go back to the client — the raw token never reaches client-side JS.
 */
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { BackendApiError } from "@/lib/api/backend";
import { loginAgainstBackend } from "@/lib/api/auth-client";
import type { ClientLoginResult, LoginRequest } from "@/lib/api/types";
import { SESSION_COOKIE_NAME, sessionCookieOptions } from "@/lib/auth/session";

export async function POST(request: Request) {
  let body: LoginRequest;
  try {
    body = (await request.json()) as LoginRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.username || !body.password) {
    return NextResponse.json(
      { detail: "Username and password are required" },
      { status: 400 },
    );
  }

  try {
    const backendResult = await loginAgainstBackend(body);

    const cookieStore = await cookies();
    cookieStore.set(SESSION_COOKIE_NAME, backendResult.access_token, sessionCookieOptions());

    const clientResult: ClientLoginResult = {
      role: backendResult.role,
      user_id: backendResult.user_id,
    };
    return NextResponse.json(clientResult, { status: 200 });
  } catch (err) {
    if (err instanceof BackendApiError) {
      if (err.status >= 500) {
        // The backend itself errored (5xx) — not a credentials problem.
        // Surface a distinct status so the client renders "service
        // unavailable" rather than "wrong password".
        return NextResponse.json(
          { detail: "Service temporarily unavailable" },
          { status: 502 },
        );
      }
      // Genuine credential failure (backend 401, or any other 4xx from
      // /auth/login). Deliberately re-use the backend's own generic
      // message (see auth-client.ts) rather than distinguishing failure
      // modes here — don't reintroduce a username-enumeration signal at
      // this layer.
      return NextResponse.json({ detail: err.message }, { status: 401 });
    }
    // Backend unreachable, network error, etc. — not a credentials
    // problem, so a distinct status the login page can render as
    // "service unavailable" rather than "wrong password".
    return NextResponse.json(
      { detail: "Unable to reach the authentication service" },
      { status: 502 },
    );
  }
}
