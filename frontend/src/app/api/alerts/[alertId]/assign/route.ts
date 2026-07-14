/**
 * BFF proxy for `PATCH /alerts/{alert_id}/assign`
 * (`backend/api/routes/alerts.py`, Admin/Compliance only). Manual
 * (re)assignment, driving the assign dialog and bulk-assign bar.
 *
 * Next.js 16 dynamic route param convention (confirmed against
 * `node_modules/next/dist/docs/01-app/03-api-reference/03-file-
 * conventions/route.md` rather than assumed — this codebase already got
 * bitten once assuming stale Next.js semantics in Phase 13, per that
 * phase's `middleware` vs `proxy` note): `params` is a `Promise`, same as
 * Next.js 15, and must be awaited.
 */
import { NextResponse } from "next/server";

import { BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { assignAlert } from "@/lib/api/alerts-client";
import type { AssignAlertRequest } from "@/lib/api/types";

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ alertId: string }> },
) {
  const { alertId } = await params;

  let body: AssignAlertRequest;
  try {
    body = (await request.json()) as AssignAlertRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.investigator_id) {
    return NextResponse.json({ detail: "investigator_id is required" }, { status: 400 });
  }

  try {
    const result = await assignAlert(alertId, body.investigator_id);
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
