/**
 * BFF proxy for `GET /cases/{case_id}/accounts/{account_id}/graph`
 * (`backend/api/routes/l2.py`) — the Investigation Graph's data source
 * (ROADMAP Phase 17). `channels`/`roles` are repeated query params
 * (`?channels=UPI&channels=NEFT`), read via `getAll` rather than
 * `Object.fromEntries` (which would silently drop all but the last value) —
 * same convention `app/api/audit-log/route.ts` already established.
 * Backend-error mapping is centralized in `route-handler.ts`.
 */
import { NextRequest, NextResponse } from "next/server";

import { getAccountGraph } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { GraphQueryParams } from "@/lib/api/types";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ caseId: string; accountId: string }> },
) {
  const { caseId, accountId } = await params;
  const searchParams = request.nextUrl.searchParams;
  const channels = searchParams.getAll("channels");
  const roles = searchParams.getAll("roles");

  const query: GraphQueryParams = {
    radius: searchParams.get("radius") ? Number(searchParams.get("radius")) : undefined,
    suspicious_only: searchParams.get("suspicious_only") === "true",
    min_risk_score: searchParams.get("min_risk_score")
      ? Number(searchParams.get("min_risk_score"))
      : undefined,
    min_amount: searchParams.get("min_amount") ? Number(searchParams.get("min_amount")) : undefined,
    max_amount: searchParams.get("max_amount") ? Number(searchParams.get("max_amount")) : undefined,
    start: searchParams.get("start") ?? undefined,
    end: searchParams.get("end") ?? undefined,
    channels: channels.length > 0 ? channels : undefined,
    direction: (searchParams.get("direction") as "in" | "out" | null) ?? undefined,
    roles: roles.length > 0 ? roles : undefined,
    prior_sar_only: searchParams.get("prior_sar_only") === "true",
  };

  return withBackendErrorMapping(async () => {
    const result = await getAccountGraph(caseId, accountId, query);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}
