/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/geo-risk`
 * (`backend/api/routes/cases.py`) — inline row inside the Customer Snapshot
 * card (L1 Triage), fetched via its own call since it's a separate backend
 * route.
 */
import { NextResponse } from "next/server";

import { getGeoRisk } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getGeoRisk(caseId, accountId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
