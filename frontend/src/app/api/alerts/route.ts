/**
 * BFF proxy for `GET /alerts` (`backend/api/routes/alerts.py`) — the
 * Dashboard alert table's data source. The browser calls this route (never
 * the FastAPI backend directly — no CORS there); this route forwards the
 * query string as-is and lets the backend do all filtering/sorting/
 * pagination and RBAC. Mirrors `app/api/auth/login/route.ts`'s error-
 * mapping pattern.
 */
import { NextRequest, NextResponse } from "next/server";

import { BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { listAlerts } from "@/lib/api/alerts-client";

export async function GET(request: NextRequest) {
  const params = Object.fromEntries(request.nextUrl.searchParams);

  try {
    const result = await listAlerts(params);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      return NextResponse.json({ detail: err.message }, { status: 502 });
    }
    if (err instanceof BackendApiError) {
      return NextResponse.json({ detail: err.message }, { status: err.status });
    }
    throw err;
  }
}
