/**
 * BFF proxy for `GET /cases/{case_id}` (`backend/api/routes/cases.py::
 * get_case`) — single-case lookup, reachable for ANY case by ANY
 * authenticated user (`require_case_read_access` server-side). Data source
 * for opening a Similar Case / Previous Investigation History row as a real
 * tab (`similar-cases.tsx`/`previous-alerts.tsx`) and for
 * `workspace-shell.tsx`'s `?case=` deep link once a fuller lookup than the
 * initial queue fetch is needed. Mirrors `app/api/cases/route.ts`'s
 * convention.
 */
import { NextResponse } from "next/server";

import { getCase } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await getCase(caseId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
