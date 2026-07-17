/**
 * BFF proxy for `PATCH /cases/{case_id}/evidence/{evidence_id}/pin`
 * (`backend/api/routes/l2.py::pin_evidence`) — Evidence Management
 * (ROADMAP Phase 18). One-directional: always sets `pinned=true`, no
 * request body, no "unpin" counterpart (matches the backend route, which
 * has none either).
 */
import { NextResponse } from "next/server";

import { pinEvidence } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ caseId: string; evidenceId: string }> },
) {
  const { caseId, evidenceId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await pinEvidence(caseId, evidenceId);
    return NextResponse.json(result, { status: 200 });
  });
}
