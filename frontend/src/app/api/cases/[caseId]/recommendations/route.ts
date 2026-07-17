/**
 * BFF proxy for `POST /cases/{case_id}/recommendations`
 * (`backend/api/routes/recommendations.py`) — the floating AI
 * Recommendations widget's "Generate" action. No request body. Real,
 * billed LLM call server-side — never fetched automatically, only in
 * response to an explicit click (`ai-widget/recommendations-panel.tsx`).
 *
 * Assignment-gated (`require_case_access`) server-side, same as
 * `/decision`/`/start` — a 403 here means the case isn't assigned to the
 * caller, which the widget anticipates and disables "Generate" for rather
 * than letting the user hit a raw 403. 503 if the LLM gateway is
 * unconfigured, 502 if the model failed to produce valid structured
 * output — both forwarded as-is via `withBackendErrorMapping`.
 */
import { NextResponse } from "next/server";

import { generateRecommendations } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await generateRecommendations(caseId);
    return NextResponse.json(result, { status: 200 });
  });
}
