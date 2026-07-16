import { Suspense } from "react";
import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { listCases } from "@/lib/api/cases-client";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import type { CaseListResponse } from "@/lib/api/types";

// No filters/sort — must match `CaseQueue`'s own initial state (Phase 15
// has no pagination UI, see that component's `QUEUE_LIMIT` docstring) so
// this first paint and the queue's own client-side re-fetches agree on
// what "the default view" means, same reasoning as `dashboard/page.tsx`'s
// `DEFAULT_ALERTS_PARAMS`.
const DEFAULT_CASES_PARAMS = { limit: 200, offset: 0 };

/**
 * Thin Server Component: fetches the current user's role-scoped case queue
 * via `listCases()` server-side for first paint (mirrors
 * `dashboard/page.tsx`'s pattern exactly), then hands off to
 * `WorkspaceShell`, which owns the Zustand tab store and all client-side
 * interactivity (queue filtering, tab open/close, `?case=` deep-link
 * resolution) from there.
 *
 * `WorkspaceShell` reads `useSearchParams()` — wrapped in `Suspense` per
 * Next's documented recommendation for a Client Component that calls it
 * (this route is already fully dynamic via the `(app)` layout's own
 * `cookies()` call, so this isn't required to avoid a build failure here,
 * but it's cheap and matches the framework's stated best practice).
 */
export default async function WorkspacePage() {
  let queue: CaseListResponse | null;
  try {
    queue = await listCases(DEFAULT_CASES_PARAMS);
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      return <BackendUnavailable />;
    }
    throw err;
  }

  if (queue === null) {
    // The `(app)` layout already guarantees an authenticated session by the
    // time this page renders — see `dashboard/page.tsx`'s identical
    // reasoning for why a `null` here just means the token expired in the
    // brief window since that check, and isn't worth a bespoke UI.
    return null;
  }

  return (
    <Suspense fallback={<div className="p-6" />}>
      <WorkspaceShell initialQueue={queue} />
    </Suspense>
  );
}

function BackendUnavailable() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center p-4">
      <Alert variant="destructive" className="max-w-md">
        <AlertTriangle />
        <AlertTitle>Service temporarily unavailable</AlertTitle>
        <AlertDescription>
          TraceX couldn&apos;t reach the cases service. Try reloading this page in a moment.
        </AlertDescription>
      </Alert>
    </div>
  );
}
