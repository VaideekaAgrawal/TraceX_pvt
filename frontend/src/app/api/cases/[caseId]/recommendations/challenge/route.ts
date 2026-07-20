/**
 * BFF proxy for `POST /cases/{case_id}/recommendations/challenge`
 * (`backend/api/routes/recommendations.py`) — the floating AI
 * Recommendations widget's cross-question flow. Body: `{question: string}`.
 * Same assignment-gated / 503 / 502 shape as `recommendations/route.ts`
 * (this file's sibling) — see that file's docstring.
 */
import { NextResponse } from "next/server";

import { challengeRecommendation } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { ChallengeRequest } from "@/lib/api/types";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  let body: ChallengeRequest;
  try {
    body = (await request.json()) as ChallengeRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.question || !body.question.trim()) {
    return NextResponse.json({ detail: "question is required" }, { status: 400 });
  }

  return withBackendErrorMapping(async () => {
    const result = await challengeRecommendation(caseId, body);
    return NextResponse.json(result, { status: 200 });
  });
}
