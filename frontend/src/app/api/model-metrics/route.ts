/**
 * BFF proxy for `GET /model-metrics` (`backend/api/routes/governance.py`)
 * — model governance surfacing (ROADMAP Phase 12 backend / Phase 22
 * frontend). Admin/Compliance only server-side; this route just forwards
 * the real 401/403 if it's ever hit by a non-admin session, same posture
 * as `app/api/watchlist/route.ts`'s `GET`.
 */
import { NextResponse } from "next/server";

import { getModelMetrics } from "@/lib/api/governance-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET() {
  return withBackendErrorMapping(async () => {
    const result = await getModelMetrics();
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
