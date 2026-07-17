/**
 * BFF proxy for `GET /cases/{case_id}/relationships` (`backend/api/routes/
 * l2.py::get_case_relationships`) — the Relationship Explorer's data source
 * (ROADMAP Phase 18). Read-only, no query params to forward.
 */
import { NextResponse } from "next/server";

import { getCaseRelationships } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getCaseRelationships(caseId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
