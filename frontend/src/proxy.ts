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

const PUBLIC_PATHS = ["/login"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const hasSession = request.cookies.has(SESSION_COOKIE_NAME);
  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  // Every path except Next.js internals, static assets, and our own
  // BFF auth routes (those must stay reachable while logged out — the
  // login page needs to be able to POST to `/api/auth/login`).
  matcher: ["/((?!_next/static|_next/image|favicon.ico|api/auth).*)"],
};
