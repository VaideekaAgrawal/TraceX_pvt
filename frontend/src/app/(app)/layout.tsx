import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import { getCurrentUser } from "@/lib/api/auth-client";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { TopNav } from "@/components/shell/top-nav";

/**
 * Guards every page under this route group (Dashboard, Investigation
 * Workspace, My Center). `proxy.ts` already redirects unauthenticated
 * requests based on cookie *presence*; this layout does the real
 * validation by calling `GET /auth/me` server-side (memoized with the
 * identical call the root layout already made this render pass, so this
 * isn't a second network round trip in practice) and reacts to an
 * expired/invalid token — the case proxy.ts can't detect from presence
 * alone.
 *
 * A present-but-invalid cookie redirects through `/api/auth/session-
 * expired` (a Route Handler) rather than deleting the cookie here
 * directly — Next.js doesn't allow `cookies().delete()` during Server
 * Component rendering, only inside a Server Function or Route Handler
 * (see that route's docstring for the exact framework constraint).
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await getCurrentUser();

  if (!user) {
    const cookieStore = await cookies();
    if (cookieStore.has(SESSION_COOKIE_NAME)) {
      redirect("/api/auth/session-expired");
    }
    redirect("/login");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <TopNav />
      <main className="flex-1">{children}</main>
    </div>
  );
}
