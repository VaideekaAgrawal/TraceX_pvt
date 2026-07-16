/**
 * BFF proxy for `GET /cases/{case_id}/summary/alerts`
 * (`backend/api/routes/cases.py`) — L1 Triage's Alert Summary section.
 * Mirrors `app/api/cases/route.ts`'s exact convention.
 */
import { NextResponse } from "next/server";

import { getAlertSummary } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getAlertSummary(caseId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
