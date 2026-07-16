/**
 * BFF proxy for `GET /cases/{case_id}/transactions/search` (case-wide,
 * `backend/api/routes/l2.py`) — the Transaction Explorer's case-wide search
 * mode (ROADMAP Phase 17). Query parsing shared with the account-scoped
 * sibling route via `parseTransactionSearchParams`.
 */
import { NextRequest, NextResponse } from "next/server";

import { searchCaseTransactions } from "@/lib/api/case-detail-client";
import { parseTransactionSearchParams } from "@/lib/api/query-params";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;
  const query = parseTransactionSearchParams(request);

  return withBackendErrorMapping(async () => {
    const result = await searchCaseTransactions(caseId, query);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
