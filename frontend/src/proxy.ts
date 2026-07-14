/**
 * Route guard: redirects to `/login` when the session cookie is absent on
 * a protected path.
 *
 * Judgment call: the task spec (and FRONTEND_ROADMAP.md) describes this as
 * `middleware.ts`, but the Next.js version actually installed here
 * (16.2.10) deprecated the `middleware` file convention in favor of
 * `proxy` (same runtime behavior, renamed export/file — see
 * `node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md`,
 * "Migration to Proxy"). `middleware.ts` still technically resolves in
 * this version for backward compatibility, but building against a
 * convention the installed framework version itself deprecates on day one
 * would just create near-term churn. Using `proxy.ts` here instead.
 *
 * This is presence-only ("is there a cookie at all") — it does NOT
 * validate the JWT (expired/tampered token). That's the root layout's job:
 * it calls the real `GET /auth/me` server-side, and a 401 there redirects
 * to `/login` and clears the cookie (see `app/(app)/layout.tsx`). Proxy
 * can't do that check itself without importing backend-calling code into
 * the proxy runtime, which is unnecessary for a presence check.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { DEFAULT_LANDING_PATH, NEXT_PARAM, PATHNAME_HEADER } from "@/lib/auth/redirect";

const PUBLIC_PATHS = ["/login"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Forward the current pathname to Server Components downstream (they
  // can't read the incoming request's URL directly, only `next/headers`)
  // so `(app)/layout.tsx` can preserve it as `next` when it redirects a
  // present-but-invalid cookie to `/api/auth/session-expired`.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set(PATHNAME_HEADER, pathname);
  const forwarded = { request: { headers: requestHeaders } };

  if (isPublicPath(pathname)) {
    return NextResponse.next(forwarded);
  }

  const hasSession = request.cookies.has(SESSION_COOKIE_NAME);
  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set(NEXT_PARAM, pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (pathname === "/") {
    // Cheap fix for a double backend round-trip: `/` (`app/page.tsx`) has
    // no content of its own, it just picks the default landing page.
    // Redirecting here — before any Server Component renders — means the
    // root layout's `getCurrentUser()` call for this pass is never made
    // (and therefore never wastefully discarded), instead of rendering
    // `/` first (root layout calls `/auth/me`) only to immediately
    // `redirect()` to `/dashboard`, which calls `/auth/me` again.
    return NextResponse.redirect(new URL(DEFAULT_LANDING_PATH, request.url));
  }

  // IMPORTANT INVARIANT: the check above is presence-only ("is there a
  // cookie at all") — it does NOT validate the JWT. Real token validation
  // (expired/tampered token) only happens in `(app)/layout.tsx` via the
  // real `GET /auth/me` call. Today's safety therefore depends entirely on
  // every protected page living under the `(app)/` route group. Any new
  // protected route MUST be added under `(app)/`, or requests to it will
  // pass this check unauthenticated and render without real validation.
  return NextResponse.next(forwarded);
}

export const config = {
  // Every path except Next.js internals, static assets, and our own
  // BFF auth routes (those must stay reachable while logged out — the
  // login page needs to be able to POST to `/api/auth/login`).
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/auth).*)"],
};
