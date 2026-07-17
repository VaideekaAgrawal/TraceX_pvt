/**
 * BFF proxy for `GET/POST /cases/{case_id}/evidence` (`backend/api/routes/
 * l2.py`) — Evidence Management (ROADMAP Phase 18). `pinned` is a
 * tri-state filter (unset/true/false) forwarded only when the client
 * explicitly set it, matching `list_evidence`'s own `bool | None` query
 * param — `?pinned=false` is a real, distinct request from omitting the
 * param entirely (the backend returns pinned+unpinned either way, but only
 * the omitted-param form does so via one unfiltered repository call).
 */
import { NextRequest, NextResponse } from "next/server";

import { createEvidence, listEvidence } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { EvidenceCreateRequest } from "@/lib/api/types";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;
  const pinnedParam = request.nextUrl.searchParams.get("pinned");
  const pinned = pinnedParam === null ? undefined : pinnedParam === "true";

  return withBackendErrorMapping(async () => {
    const result = await listEvidence(caseId, pinned);
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

  let body: EvidenceCreateRequest;
  try {
    body = (await request.json()) as EvidenceCreateRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.type) {
    return NextResponse.json({ detail: "type is required" }, { status: 400 });
  }

  return withBackendErrorMapping(async () => {
    const result = await createEvidence(caseId, body);
    return NextResponse.json(result, { status: 201 });
  });
}
