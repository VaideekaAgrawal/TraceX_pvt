/**
 * BFF proxy for `GET /cases` (`backend/api/routes/cases.py`) — the
 * Investigation Workspace queue's data source. The browser calls this route
 * (never the FastAPI backend directly — no CORS there); this route forwards
 * the query string as-is and lets the backend do all filtering/sorting/
 * pagination and role-scoping. Backend-error mapping is centralized in
 * `route-handler.ts`. Mirrors `app/api/alerts/route.ts`'s exact convention.
 */
import { NextRequest, NextResponse } from "next/server";

import { listCases } from "@/lib/api/cases-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(request: NextRequest) {
  const params = Object.fromEntries(request.nextUrl.searchParams);

  return withBackendErrorMapping(async () => {
    const result = await listCases(params);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
