/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/profile`
 * (`backend/api/routes/l2.py`) — the Complete Customer Profile section's
 * data source (ROADMAP Phase 17).
 */
import { NextResponse } from "next/server";

import { getCustomerProfile } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getCustomerProfile(caseId, accountId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
