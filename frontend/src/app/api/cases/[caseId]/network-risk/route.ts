/**
 * BFF proxy for `GET /cases/{case_id}/network-risk` (`backend/api/routes/
 * cases.py`) — L1 Triage's Network Risk section. Lazy-computed server-side
 * on first view; see the sibling `network-risk/recompute/route.ts` for the
 * manual-refresh control.
 */
import { NextResponse } from "next/server";

import { getNetworkRisk } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getNetworkRisk(caseId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
