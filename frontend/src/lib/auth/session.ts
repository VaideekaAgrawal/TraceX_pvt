/**
 * Session-cookie contract shared by the login/logout Route Handlers, the
 * root layout, the backend fetch helper, and `proxy.ts`. This is the one
 * place the cookie name/options live — never duplicate these literals.
 *
 * Deliberately NOT marked `import "server-only"`: `proxy.ts` also needs
 * `SESSION_COOKIE_NAME` (to check for the cookie's presence) and runs in a
 * separate bundling context from ordinary Server Components, where the
 * `server-only` package's browser-condition guard can misfire. Nothing in
 * this file is actually sensitive — it's a cookie *name* and non-secret
 * options (httpOnly/secure/sameSite/maxAge), not the JWT itself. The JWT
 * stays opaque to the browser because it's set httpOnly, not because this
 * file is import-restricted — matching the BFF pattern this phase is built
 * around (see docs/ROADMAP.md Phase 13 and FRONTEND_ROADMAP.md's decision
 * to prefer a cookie over localStorage).
 */

export const SESSION_COOKIE_NAME = "tracex_session";

// `secure` only in non-dev so this still works over plain HTTP on
// localhost during development; `sameSite=lax` per the task spec (allows
// top-level navigation to carry the cookie, blocks cross-site POST/fetch
// forgery). `path=/` so every route under the Next.js origin sees it —
// required for middleware/proxy's protected-path check to work app-wide.
export function sessionCookieOptions() {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    // Mirrors the backend's own `jwt_expiry_minutes` default (8h,
    // `foundation/config.py`) so the cookie doesn't outlive the token it
    // carries. If the backend ever changes its expiry, this constant
    // should move to an env var alongside BACKEND_API_URL — not a
    // correctness issue today, just a maintenance note.
    maxAge: 60 * 60 * 8,
  };
}
