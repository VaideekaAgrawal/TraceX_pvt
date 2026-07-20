/**
 * BFF proxy for `POST /reports/{report_id}/finalize` (`backend/api/routes/
 * reports.py`) — DRAFT -> FINALIZED (ROADMAP Phase 21). Admin/Compliance
 * only server-side (`require_role`, 403 otherwise) — `str-report-panel.tsx`
 * doesn't render this control for a non-admin at all, this route's job is
 * just to forward the real 403/409 if it's ever hit anyway (e.g. a stale
 * client).
 */
import { NextResponse } from "next/server";

import { finalizeReport } from "@/lib/api/reports-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await finalizeReport(reportId);
    return NextResponse.json(result, { status: 200 });
  });
}
