/**
 * BFF proxy for `GET /alerts/workload` (`backend/api/routes/alerts.py`,
 * Admin/Compliance only). Backs the assign dialog's investigator picker
 * and the alert filter bar's "assigned to" filter. The backend is the real
 * RBAC gate — an Investigator hitting this route directly gets the
 * backend's 403 forwarded as-is, not silently swallowed.
 */
import { NextResponse } from "next/server";

import { BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { getWorkload } from "@/lib/api/alerts-client";

export async function GET() {
  try {
    const result = await getWorkload();
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
