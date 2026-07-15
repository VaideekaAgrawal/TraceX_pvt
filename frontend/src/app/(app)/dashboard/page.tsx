import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { DashboardContent } from "@/components/dashboard/dashboard-content";
import { listAlerts } from "@/lib/api/alerts-client";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { getDashboardSummary } from "@/lib/api/dashboard-client";
import type { AlertListParams, AlertListResponse, DashboardSummaryResponse } from "@/lib/api/types";

// Must match `AlertTable`'s own initial state (no filters/sort, `limit=25,
// offset=0`) — this first paint and the table's own client-side re-fetches
// need to agree on what "the default view" means, or the first render
// would visibly jump the moment the table's effect re-fetches.
const DEFAULT_ALERTS_PARAMS: AlertListParams = { limit: 25, offset: 0 };

/**
 * Thin Server Component: calls the server-only clients directly (no
 * client round-trip for first paint) and hands the results to
 * `DashboardContent`, which owns all client-side interactivity from here.
 *
 * Data-fetching happens in a `try`/`catch` up front, with JSX construction
 * kept out of that block (an ESLint rule here flags JSX-in-try/catch,
 * since a rendering error in that JSX wouldn't actually be caught by it —
 * only awaited data-fetching errors are real candidates for this pattern).
 */
export default async function DashboardPage() {
  let summary: DashboardSummaryResponse | null;
  let alerts: AlertListResponse | null;
  try {
    [summary, alerts] = await Promise.all([
      getDashboardSummary(),
      listAlerts(DEFAULT_ALERTS_PARAMS),
    ]);
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      // Mirrors `(app)/layout.tsx`'s `BackendUnavailable` state — a 5xx/
      // network failure here says nothing about the session, so this
      // renders a distinct "try again" state rather than crashing the
      // route.
      return <BackendUnavailable />;
    }
    throw err;
  }

  if (summary === null || alerts === null) {
    // The `(app)` layout already guarantees an authenticated session by
    // the time this page renders (it calls `GET /auth/me` itself) — a
    // `null` here would only mean the token expired in the brief window
    // between that check and this fetch. Not worth a bespoke UI: render
    // nothing and let the next navigation re-trigger the layout's own
    // session-expiry handling.
    return null;
  }

  return <DashboardContent initialSummary={summary} initialAlerts={alerts} />;
}

function BackendUnavailable() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center p-4">
      <Alert variant="destructive" className="max-w-md">
        <AlertTriangle />
        <AlertTitle>Service temporarily unavailable</AlertTitle>
        <AlertDescription>
          TraceX couldn&apos;t reach the alerts/dashboard service. Try reloading this page in a
          moment.
        </AlertDescription>
      </Alert>
    </div>
  );
}
