/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/explanation`
 * (`backend/api/routes/cases.py`) — L1 Triage's AI panel, account-level tab.
 * `force=true` bypasses the backend's response cache (exposed here as a
 * "regenerate" control). Mirrors `app/api/cases/route.ts`'s convention.
 */
import { NextRequest, NextResponse } from "next/server";

import { getAccountExplanation } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;
  const force = request.nextUrl.searchParams.get("force") === "true";

  return withBackendErrorMapping(async () => {
    const result = await getAccountExplanation(caseId, accountId, force);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
