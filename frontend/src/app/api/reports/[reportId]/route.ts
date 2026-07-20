/**
 * BFF proxy for `GET/PATCH /reports/{report_id}` (`backend/api/routes/
 * reports.py`) — single-report lookup + DRAFT narrative edit (ROADMAP
 * Phase 21). Both routes re-apply the same case-access check the
 * generating case's routes use (assigned investigator, or Admin/
 * Compliance bypass) — a 403/404 here means "not your case," forwarded
 * as-is via `withBackendErrorMapping`, same posture as every other BFF
 * route in this codebase.
 */
import { NextResponse } from "next/server";

import { editReportNarrative, getReport } from "@/lib/api/reports-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { EditNarrativeRequest } from "@/lib/api/types";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getReport(reportId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await params;

  let body: EditNarrativeRequest;
  try {
    body = (await request.json()) as EditNarrativeRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.narrative || !body.narrative.trim()) {
    return NextResponse.json({ detail: "narrative is required" }, { status: 400 });
  }

  return withBackendErrorMapping(async () => {
    const result = await editReportNarrative(reportId, body);
    return NextResponse.json(result, { status: 200 });
  });
}
