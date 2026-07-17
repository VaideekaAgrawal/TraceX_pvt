/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/graph-explanation`
 * (`backend/api/routes/l2.py::get_graph_explanation`) — the AI Investigation
 * Graph explanation panel's data source (`deep/graph-explanation-panel.tsx`).
 * `force=true` bypasses the backend's response cache (a "Regenerate"
 * control), identical convention to `.../explanation/route.ts`.
 */
import { NextRequest, NextResponse } from "next/server";

import { getGraphExplanation } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;
  const force = request.nextUrl.searchParams.get("force") === "true";

  return withBackendErrorMapping(async () => {
    const result = await getGraphExplanation(caseId, accountId, force);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
