/**
 * BFF proxy for `POST /cases/{case_id}/decision` (`backend/api/routes/
 * cases.py`) — L1 Triage's role-aware Decision Panel. Role logic (who may
 * submit `close_fp`) is enforced server-side (403 if violated) — this route
 * does not re-implement that check, it just forwards the real status/detail
 * via `withBackendErrorMapping` so the frontend surfaces a real error
 * instead of a generic one (see `components/workspace/triage/decision-
 * panel.tsx`).
 */
import { NextResponse } from "next/server";

import { postDecision } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { DecisionRequest } from "@/lib/api/types";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  let body: DecisionRequest;
  try {
    body = (await request.json()) as DecisionRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.decision || !body.reason || !body.reason.trim()) {
    return NextResponse.json({ detail: "decision and reason are required" }, { status: 400 });
  }

  return withBackendErrorMapping(async () => {
    const result = await postDecision(caseId, body);
    return NextResponse.json(result, { status: 200 });
  });
}
