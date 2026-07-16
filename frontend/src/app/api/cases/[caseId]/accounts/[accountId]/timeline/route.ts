/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/timeline`
 * (`backend/api/routes/l2.py`) — the Investigation Timeline's data source
 * (ROADMAP Phase 17). Mirrors `app/api/cases/[caseId]/accounts/[accountId]/
 * money-flow/route.ts`'s exact convention.
 */
import { NextRequest, NextResponse } from "next/server";

import { getAccountTimeline } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;
  const searchParams = request.nextUrl.searchParams;

  return withBackendErrorMapping(async () => {
    const result = await getAccountTimeline(caseId, accountId, {
      start: searchParams.get("start") ?? undefined,
      end: searchParams.get("end") ?? undefined,
    });
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
