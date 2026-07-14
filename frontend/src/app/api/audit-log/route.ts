/**
 * BFF proxy for `GET /audit-log` (`backend/api/routes/audit.py`). Backs
 * both the Dashboard/My Center audit views and the notification bell's
 * curated `action`-allowlist feed — `action` is a repeated query param
 * (`?action=case_assigned&action=escalated&...`), read via `getAll` rather
 * than `Object.fromEntries` (which would silently drop all but the last
 * value).
 */
import { NextRequest, NextResponse } from "next/server";

import { BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { listAuditLog } from "@/lib/api/audit-client";
import type { AuditLogParams } from "@/lib/api/types";

export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const action = searchParams.getAll("action");

  const params: AuditLogParams = {
    case_id: searchParams.get("case_id") ?? undefined,
    actor_id: searchParams.get("actor_id") ?? undefined,
    action: action.length > 0 ? action : undefined,
    since: searchParams.get("since") ?? undefined,
    limit: searchParams.get("limit") ?? undefined,
    offset: searchParams.get("offset") ?? undefined,
  };

  try {
    const result = await listAuditLog(params);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      return NextResponse.json({ detail: err.message }, { status: 502 });
    }
    if (err instanceof BackendApiError) {
      return NextResponse.json({ detail: err.message }, { status: err.status });
    }
    throw err;
  }
}
