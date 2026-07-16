/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/transaction-purpose`
 * (`backend/api/routes/cases.py`) — same card as Transaction Summary in
 * L1 Triage.
 */
import { NextResponse } from "next/server";

import { getTransactionPurpose } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getTransactionPurpose(caseId, accountId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
