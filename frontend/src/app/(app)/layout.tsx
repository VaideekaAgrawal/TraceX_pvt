import { redirect } from "next/navigation";
import { cookies, headers } from "next/headers";
import { AlertTriangle } from "lucide-react";

import { getCurrentUser, BackendUnavailableError } from "@/lib/api/auth-client";
import { SESSION_COOKIE_NAME } from "@/lib/auth/session";
import { NEXT_PARAM, PATHNAME_HEADER } from "@/lib/auth/redirect";
import { TopNav } from "@/components/shell/top-nav";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

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
  let user;
  try {
    user = await getCurrentUser();
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      // The backend itself errored (5xx/network failure) — this says
      // nothing about whether the session is valid, so do NOT route this
      // through the logout/session-expired path (that would destroy a
      // perfectly good cookie). Render a distinct "try again" state
      // instead of crashing the whole route group.
      return <BackendUnavailable />;
    }
    throw err;
  }

  if (!user) {
    const cookieStore = await cookies();
    if (cookieStore.has(SESSION_COOKIE_NAME)) {
      const headerStore = await headers();
      const pathname = headerStore.get(PATHNAME_HEADER);
      const sessionExpiredUrl = pathname
        ? `/api/auth/session-expired?${NEXT_PARAM}=${encodeURIComponent(pathname)}`
        : "/api/auth/session-expired";
      redirect(sessionExpiredUrl);
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

function BackendUnavailable() {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Alert variant="destructive" className="max-w-md">
        <AlertTriangle />
        <AlertTitle>Service temporarily unavailable</AlertTitle>
        <AlertDescription>
          TraceX couldn&apos;t reach the authentication service. Your session may still be
          valid — try reloading this page in a moment.
        </AlertDescription>
      </Alert>
    </div>
  );
}
