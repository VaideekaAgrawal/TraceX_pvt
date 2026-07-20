/**
 * BFF proxy for `POST /copilot/ask` (`backend/api/routes/copilot.py`) — the
 * floating AI widget's Copilot chat tab. Body: `{question: string}`. Cross-
 * case, unlike the sibling `recommendations/[caseId]` routes: no `caseId` in
 * this path, the backend scopes tool calls to the caller's own cases
 * internally. Real, billed LLM call — only ever fired from an explicit chat
 * send, never on mount. 503 if the LLM gateway is unconfigured, 502 if the
 * model failed to produce valid structured output — both forwarded as-is via
 * `withBackendErrorMapping`.
 */
import { NextResponse } from "next/server";

import { askCopilot } from "@/lib/api/copilot-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { CopilotAskRequest } from "@/lib/api/types";

export async function POST(request: Request) {
  let body: CopilotAskRequest;
  try {
    body = (await request.json()) as CopilotAskRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.question || !body.question.trim()) {
    return NextResponse.json({ detail: "question is required" }, { status: 400 });
  }

  return withBackendErrorMapping(async () => {
    const result = await askCopilot(body);
    return NextResponse.json(result, { status: 200 });
  });
}
