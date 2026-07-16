/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/behavior`
 * (`backend/api/routes/l2.py`) — the Historical Behaviour Analysis
 * section's data source (ROADMAP Phase 17).
 */
import { NextResponse } from "next/server";

import { getAccountBehavior } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getAccountBehavior(caseId, accountId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
