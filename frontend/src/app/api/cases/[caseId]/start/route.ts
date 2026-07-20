/**
 * BFF proxy for `POST /cases/{case_id}/start` (`backend/api/routes/
 * cases.py::start_investigation`) — the `ASSIGNED -> IN_PROGRESS` step, no
 * request body. Assignment-gated server-side (`require_case_access`), so
 * this can still 403/409 for a caller without access or a case not
 * currently `ASSIGNED`; `case-tab-content.tsx`'s auto-start effect treats
 * both as best-effort and ignores them. Mirrors `network-risk/recompute/
 * route.ts`'s "POST, no body" convention.
 */
import { NextResponse } from "next/server";

import { startInvestigation } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await startInvestigation(caseId);
    return NextResponse.json(result, { status: 200 });
  });
}
