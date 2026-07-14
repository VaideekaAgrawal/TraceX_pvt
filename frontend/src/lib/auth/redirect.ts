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
 * True only for same-origin, path-relative targets: must start with exactly
 * one `/` (not `//`, which browsers resolve as a protocol-relative absolute
 * URL to a different origin) and must not be an empty string. This is the
 * one place that decides whether an attacker-controlled `next` value is
 * safe to redirect to.
 */
export function isSafeRedirectTarget(next: string | null | undefined): next is string {
  if (!next) {
    return false;
  }
  return next.startsWith("/") && !next.startsWith("//");
}

/** Convenience: the validated `next` target, or the default landing path. */
export function resolveRedirectTarget(next: string | null | undefined): string {
  return isSafeRedirectTarget(next) ? next : DEFAULT_LANDING_PATH;
}
