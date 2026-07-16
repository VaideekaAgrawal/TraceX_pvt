/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/previous-alerts`
 * (`backend/api/routes/cases.py`) — L1 Triage's Previous Investigation
 * History section.
 */
import { NextResponse } from "next/server";

import { getPreviousAlerts } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getPreviousAlerts(caseId, accountId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
