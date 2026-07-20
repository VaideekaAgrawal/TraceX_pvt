import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { MonitoringSection } from "@/components/my-center/monitoring-section";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { listWatchlist } from "@/lib/api/watchlist-client";
import type { WatchlistEntryModel } from "@/lib/api/types";

/**
 * My Center → Monitoring (ROADMAP Phase 21), replacing the prior flat
 * placeholder. Server Component fetches `GET /watchlist` for first paint
 * (mirrors `dashboard/page.tsx`/`workspace/page.tsx`'s exact pattern), then
 * hands off to `MonitoringSection` for all client-side interactivity
 * (add/remove, alert-click-through navigation).
 *
 * The placeholder this replaces also mentioned "audit logs" as a second
 * planned section — investigated before building here (per this phase's
 * task brief) and confirmed NOT built anywhere else: `notification-bell.
 * tsx` only ever surfaces a curated allowlisted feed, and `ai-widget/
 * audit-thread-panel.tsx` only surfaces one case's AI-interaction thread,
 * not a general-purpose log viewer. A full My Center audit-log tab is
 * genuinely out of scope for this phase (not requested by the Phase 21
 * task brief, which asks specifically for the Monitoring tab) — left out
 * deliberately rather than silently absorbed; noted here rather than
 * built as unplanned scope.
 */
export default async function MyCenterPage() {
  let watchlist: WatchlistEntryModel[] | null;
  try {
    watchlist = await listWatchlist();
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      return <BackendUnavailable />;
    }
    throw err;
  }

  if (watchlist === null) {
    // The `(app)` layout already guarantees an authenticated session by the
    // time this page renders — see `dashboard/page.tsx`'s identical
    // reasoning for why a `null` here just means the token expired in the
    // brief window since that check, and isn't worth a bespoke UI.
    return null;
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="font-heading text-xl font-semibold">My Center</h1>
        <p className="text-muted-foreground text-sm">
          Entities under active compliance monitoring, and the alerts raised against them since.
        </p>
      </div>

      <MonitoringSection initialEntries={watchlist} />
    </div>
  );
}

function BackendUnavailable() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center p-4">
      <Alert variant="destructive" className="max-w-md">
        <AlertTriangle />
        <AlertTitle>Service temporarily unavailable</AlertTitle>
        <AlertDescription>
          TraceX couldn&apos;t reach the watchlist service. Try reloading this page in a moment.
        </AlertDescription>
      </Alert>
    </div>
  );
}
