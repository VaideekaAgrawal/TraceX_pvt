/**
 * Clears a stale session cookie and redirects to `/login`.
 *
 * Why this exists as its own Route Handler rather than deleting the cookie
 * directly inside `app/(app)/layout.tsx`: Next.js does not allow
 * `cookies().delete()`/`.set()` during Server Component rendering — only
 * inside a Server Function or Route Handler (see
 * `node_modules/next/dist/docs/01-app/03-api-reference/04-functions/cookies.md`,
 * "Understanding Cookie Behavior in Server Components"). The guarded
 * layout detects an invalid/expired token (a cookie is present but
 * `GET /auth/me` still returned 401) and redirects here instead of
 * directly to `/login`, so the stale cookie actually gets cleared before
 * the browser lands on the login page.
 */
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { SESSION_COOKIE_NAME } from "@/lib/auth/session";

export async function GET(request: Request) {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE_NAME);

  const url = new URL(request.url);
  const next = url.searchParams.get("next");
  const loginUrl = new URL("/login", url.origin);
  if (next) {
    loginUrl.searchParams.set("next", next);
  }
  return NextResponse.redirect(loginUrl);
}
