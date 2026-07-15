/**
 * BFF proxy for `GET /dashboard/summary` (`backend/api/routes/
 * dashboard.py`). Used by the Client Component dashboard wrapper to
 * refresh the summary cards after a successful assign, without a full page
 * reload (the initial paint calls `getDashboardSummary()` directly from
 * the Server Component instead — this route only exists for the
 * client-side refresh path). Backend-error mapping is centralized in
 * `route-handler.ts` (see that file for why).
 */
import { NextResponse } from "next/server";

import { getDashboardSummary } from "@/lib/api/dashboard-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET() {
  return withBackendErrorMapping(async () => {
    const result = await getDashboardSummary();
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
