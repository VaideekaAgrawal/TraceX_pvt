/**
 * BFF proxy for `GET /alerts` (`backend/api/routes/alerts.py`) — the
 * Dashboard alert table's data source. The browser calls this route (never
 * the FastAPI backend directly — no CORS there); this route forwards the
 * query string as-is and lets the backend do all filtering/sorting/
 * pagination and RBAC. Backend-error mapping is centralized in
 * `route-handler.ts` (see that file for why).
 */
import { NextRequest, NextResponse } from "next/server";

import { listAlerts } from "@/lib/api/alerts-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(request: NextRequest) {
  const params = Object.fromEntries(request.nextUrl.searchParams);

  return withBackendErrorMapping(async () => {
    const result = await listAlerts(params);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
