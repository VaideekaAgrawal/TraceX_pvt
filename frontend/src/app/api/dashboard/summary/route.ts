/**
 * BFF proxy for `GET /dashboard/summary` (`backend/api/routes/
 * dashboard.py`). Used by the Client Component dashboard wrapper to
 * refresh the summary cards after a successful assign, without a full page
 * reload (the initial paint calls `getDashboardSummary()` directly from
 * the Server Component instead — this route only exists for the
 * client-side refresh path).
 */
import { NextResponse } from "next/server";

import { BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { getDashboardSummary } from "@/lib/api/dashboard-client";

export async function GET() {
  try {
    const result = await getDashboardSummary();
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
