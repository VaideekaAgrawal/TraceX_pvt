/**
 * BFF proxy for `DELETE /watchlist/{entry_id}` (`backend/api/routes/
 * watchlist.py`) — deactivates a watchlist entry (ROADMAP Phase 21).
 * Admin/Compliance only server-side (403 otherwise).
 *
 * This is this codebase's first BFF Route Handler exporting a `DELETE`
 * verb — every prior mutating route here has been `POST`/`PATCH`. Follows
 * `withBackendErrorMapping`'s exact same wrapper as every other route;
 * the only real difference is the success response, which forwards the
 * backend's own `204 No Content` (no JSON body to return) rather than
 * `NextResponse.json(...)`.
 */
import { NextResponse } from "next/server";

import { removeWatchlistEntry } from "@/lib/api/watchlist-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ entryId: string }> },
) {
  const { entryId } = await params;

  return withBackendErrorMapping(async () => {
    await removeWatchlistEntry(entryId);
    return new NextResponse(null, { status: 204 });
  });
}
