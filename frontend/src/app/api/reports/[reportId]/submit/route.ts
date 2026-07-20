/**
 * BFF proxy for `POST /reports/{report_id}/submit` (`backend/api/routes/
 * reports.py`) — FINALIZED -> SUBMITTED (ROADMAP Phase 21). Admin/
 * Compliance only server-side, same posture as the sibling `finalize`
 * route.
 */
import { NextResponse } from "next/server";

import { submitReport } from "@/lib/api/reports-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { SubmitReportRequest } from "@/lib/api/types";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await params;

  let body: SubmitReportRequest;
  try {
    body = (await request.json()) as SubmitReportRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.fiu_reference || !body.fiu_reference.trim()) {
    return NextResponse.json({ detail: "fiu_reference is required" }, { status: 400 });
  }

  return withBackendErrorMapping(async () => {
    const result = await submitReport(reportId, body);
    return NextResponse.json(result, { status: 200 });
  });
}
