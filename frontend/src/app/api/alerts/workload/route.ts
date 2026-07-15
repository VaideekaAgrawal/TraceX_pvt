/**
 * BFF proxy for `GET /alerts/workload` (`backend/api/routes/alerts.py`,
 * Admin/Compliance only). Backs the assign dialog's investigator picker
 * and the alert filter bar's "assigned to" filter. The backend is the real
 * RBAC gate — an Investigator hitting this route directly gets the
 * backend's 403 forwarded as-is, not silently swallowed (via
 * `route-handler.ts`'s centralized mapping).
 */
import { NextResponse } from "next/server";

import { getWorkload } from "@/lib/api/alerts-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET() {
  return withBackendErrorMapping(async () => {
    const result = await getWorkload();
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
