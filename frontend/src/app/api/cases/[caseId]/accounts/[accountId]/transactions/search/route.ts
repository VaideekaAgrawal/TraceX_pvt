/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/transactions/
 * search` (account-scoped, `backend/api/routes/l2.py`) — the Transaction
 * Explorer's account-scoped search mode (ROADMAP Phase 17). Query parsing
 * shared with the case-wide sibling route via `parseTransactionSearchParams`.
 */
import { NextRequest, NextResponse } from "next/server";

import { searchAccountTransactions } from "@/lib/api/case-detail-client";
import { parseTransactionSearchParams } from "@/lib/api/query-params";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;
  const query = parseTransactionSearchParams(request);

  return withBackendErrorMapping(async () => {
    const result = await searchAccountTransactions(caseId, accountId, query);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
