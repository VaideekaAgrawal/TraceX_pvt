/**
 * BFF proxy for `GET /cases/{case_id}/similar-cases` (`backend/api/routes/
 * cases.py`) — L1 Triage's compact top-3 Similar Historical Cases card.
 * Forwards `top_k` (defaults to 3 here, not the backend's own default of 5,
 * per this phase's compact-card scope).
 */
import { NextRequest, NextResponse } from "next/server";

import { getSimilarCases } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;
  const topKParam = request.nextUrl.searchParams.get("top_k");
  const topK = topKParam ? Number(topKParam) : 3;

  return withBackendErrorMapping(async () => {
    const result = await getSimilarCases(caseId, Number.isFinite(topK) ? topK : 3);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
