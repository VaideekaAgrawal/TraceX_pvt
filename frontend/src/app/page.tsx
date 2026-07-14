import { redirect } from "next/navigation";

import { DEFAULT_LANDING_PATH } from "@/lib/auth/redirect";

/**
 * `/` has no content of its own — route guard (`proxy.ts`) plus the
 * `(app)` layout's `/auth/me` check already decide `/login` vs. the real
 * pages. This just picks a default authenticated landing page; if the
 * cookie is missing/invalid, `(app)/layout.tsx` bounces to `/login` from
 * there.
 *
 * In practice `proxy.ts` now redirects `/` to `DEFAULT_LANDING_PATH`
 * directly (before any Server Component renders), specifically to avoid a
 * double `/auth/me` round trip this page previously caused (root layout
 * fetches the user for this render pass, then this component immediately
 * discards it via `redirect()`, forcing a second fetch on the fresh
 * `/dashboard` render). This component is kept as a fallback for the
 * (unreachable under the current proxy matcher) case where `/` is hit
 * without going through proxy.
 */
export default function RootPage() {
  redirect(DEFAULT_LANDING_PATH);
}
