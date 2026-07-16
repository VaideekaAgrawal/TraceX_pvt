/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/transaction-summary`
 * (`backend/api/routes/cases.py`) — L1 Triage's Transaction Summary section.
 * Forwards the optional `start`/`end` date-range query params as-is.
 */
import { NextRequest, NextResponse } from "next/server";

import { getTransactionSummary } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;
  const start = request.nextUrl.searchParams.get("start") ?? undefined;
  const end = request.nextUrl.searchParams.get("end") ?? undefined;

  return withBackendErrorMapping(async () => {
    const result = await getTransactionSummary(caseId, accountId, { start, end });
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
