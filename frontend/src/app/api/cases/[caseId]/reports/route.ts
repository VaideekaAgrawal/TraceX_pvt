/**
 * BFF proxy for `GET/POST /cases/{case_id}/reports` (`backend/api/routes/
 * reports.py`) — STR/SAR generation (ROADMAP Phase 21). `POST` is a real,
 * billed LLM call and 409s server-side unless `case.status === "CLOSED_TP"`
 * — this route does not re-check that (the backend is the real gate), it
 * just forwards the real status/detail via `withBackendErrorMapping` so
 * `str-report-panel.tsx` can render the 409/503/502 distinctly instead of a
 * generic error.
 */
import { NextResponse } from "next/server";

import { generateReport, listReports } from "@/lib/api/reports-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { GenerateReportRequest } from "@/lib/api/types";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await listReports(caseId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  let body: GenerateReportRequest = {};
  try {
    const raw = await request.text();
    if (raw) body = JSON.parse(raw) as GenerateReportRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  return withBackendErrorMapping(async () => {
    const result = await generateReport(caseId, body);
    return NextResponse.json(result, { status: 201 });
  });
}
