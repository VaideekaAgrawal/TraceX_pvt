/**
 * BFF proxy for `GET /cases/{case_id}/alerts/{alert_id}/pattern-explanation`
 * (`backend/api/routes/l2.py::get_pattern_explanation`) — the Pattern
 * Explanation panel's data source (ROADMAP Phase 18). Per-alert, not
 * per-case/per-account — `alertId` is a distinct path segment. `force=true`
 * forwarded the same way `.../explanation`'s BFF route does for the L1
 * account explanation (`components/workspace/triage/ai-panel.tsx`'s
 * "Regenerate" button).
 */
import { NextRequest, NextResponse } from "next/server";

import { getPatternExplanation } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string; alertId: string }> },
) {
  const { caseId, alertId } = await params;
  const force = request.nextUrl.searchParams.get("force") === "true";

  return withBackendErrorMapping(async () => {
    const result = await getPatternExplanation(caseId, alertId, force);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
