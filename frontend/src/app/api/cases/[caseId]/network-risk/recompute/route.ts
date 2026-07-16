/**
 * BFF proxy for `POST /cases/{case_id}/network-risk/recompute`
 * (`backend/api/routes/cases.py`) — L1 Triage's manual "Recompute" control,
 * explicitly required (not optional) per the ROADMAP Phase 16 task.
 */
import { NextResponse } from "next/server";

import { recomputeNetworkRisk } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await recomputeNetworkRisk(caseId);
    return NextResponse.json(result, { status: 200 });
  });
}
