/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/money-flow`
 * (`backend/api/routes/cases.py`) — L1 Triage's Simplified Money Flow
 * section (rendered client-side as a non-interactive SVG, decision 3).
 */
import { NextResponse } from "next/server";

import { getMoneyFlow } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getMoneyFlow(caseId, accountId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
