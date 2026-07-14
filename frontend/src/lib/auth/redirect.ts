/**
 * Shared post-login redirect-target ("next") logic. This used to be
 * duplicated (and had drifted) across `proxy.ts`, `session-expired/route.ts`,
 * `login-form.tsx`, and `login/page.tsx` — one had an open-redirect bug
 * (`next.startsWith("/")` also matches protocol-relative URLs like
 * `//evil.com`, which browsers treat as absolute off-origin), another
 * silently dropped `next` entirely. Every consumer/producer of `next` should
 * go through this module instead of re-deriving the logic.
 *
 * Deliberately NOT marked `import "server-only"`: this is consumed from a
 * Client Component (`login-form.tsx`), a Server Component
 * (`login/page.tsx`), and `proxy.ts`'s separate bundling context — none of
 * these values are sensitive (a query-param key and a default path).
 */

/** Query-param key used to carry the post-login redirect target. */
export const NEXT_PARAM = "next";

/**
 * Request header `proxy.ts` sets to forward the current pathname to
 * Server Components downstream (they can't read the incoming request's URL
 * directly — only `next/headers`, which only exposes headers). Consumed by
 * `app/(app)/layout.tsx` so a mid-session expiry can still redirect back to
 * where the user was after re-login.
 */
export const PATHNAME_HEADER = "x-tracex-pathname";

/** Default authenticated landing page, used whenever `next` is absent/unsafe. */
export const DEFAULT_LANDING_PATH = "/dashboard";

/**
 * Sentinel base origin used only to resolve `next` through the real WHATWG
 * `URL` parser, never a value that's actually navigated to.
 */
const SENTINEL_ORIGIN = "http://tracex-internal.invalid";

/**
 * True only for same-origin, path-relative targets. This used to be a hand
 *-rolled `next.startsWith("/") && !next.startsWith("//")` check, which
 * blocked the obvious `//evil.com` protocol-relative bypass but missed two
 * others a live probe caught: browsers (per the WHATWG URL spec, for special
 * schemes like http/https) normalize a leading backslash to a slash
 * (`/\evil.com` -> `//evil.com`) and strip embedded tab/newline/CR
 * characters (`/\t/evil.com` -> `//evil.com`) *before* resolving the URL —
 * both defeat a plain string-prefix check while still resolving off-origin
 * in a real browser. Resolving through the real `URL` constructor (which
 * implements the same normalization) and comparing origins avoids
 * re-deriving the WHATWG parsing rules by hand and is exactly what
 * `window.location.assign`/`redirect()` will actually do with this value.
 */
export function isSafeRedirectTarget(next: string | null | undefined): next is string {
  if (!next || !next.startsWith("/")) {
    return false;
  }
  try {
    return new URL(next, SENTINEL_ORIGIN).origin === SENTINEL_ORIGIN;
  } catch {
    return false;
  }
}

/** Convenience: the validated `next` target, or the default landing path. */
export function resolveRedirectTarget(next: string | null | undefined): string {
  return isSafeRedirectTarget(next) ? next : DEFAULT_LANDING_PATH;
}
