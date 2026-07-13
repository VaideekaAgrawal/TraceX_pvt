import { redirect } from "next/navigation";

/**
 * `/` has no content of its own — route guard (`proxy.ts`) plus the
 * `(app)` layout's `/auth/me` check already decide `/login` vs. the real
 * pages. This just picks a default authenticated landing page; if the
 * cookie is missing/invalid, `(app)/layout.tsx` bounces to `/login` from
 * there.
 */
export default function RootPage() {
  redirect("/dashboard");
}
