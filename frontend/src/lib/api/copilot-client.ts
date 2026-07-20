/**
 * Typed wrapper around `backend/api/routes/copilot.py`'s `POST /copilot/ask`
 * (ROADMAP Phase 10 backend / Phase 20 frontend). Server-only — called from
 * this app's own `/api/copilot/ask` Route Handler, never directly from a
 * Client Component. Cross-case (no `case_id` in the path, unlike
 * `case-detail-client.ts`'s recommendation functions) — the backend scopes
 * every internal tool call to the calling user's own cases.
 *
 * A real, billed LLM call that persists an `ai_interactions` row (and
 * possibly a note via `write_case_note`), so — same convention as
 * `generateRecommendations`/`challengeRecommendation` — this always throws
 * on non-2xx rather than returning `null`: `BackendApiError` (401 not
 * authenticated, 502 model failed to produce a valid structured answer) or
 * `BackendUnavailableError` (503 LLM gateway unconfigured/unreachable,
 * genuine backend fault).
 */
import "server-only";

import { authedBackendFetch, BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import type { CopilotAskRequest, CopilotAskResponse } from "@/lib/api/types";

const UNAVAILABLE = "Unable to reach the Copilot service";

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

/** `POST /copilot/ask` — never auto-fired; `ai-widget/copilot-panel.tsx`
 * only calls this from an explicit chat-message submit. */
export async function askCopilot(body: CopilotAskRequest): Promise<CopilotAskResponse> {
  let response: Response | null;
  try {
    response = await authedBackendFetch("/copilot/ask", {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch {
    throw new BackendUnavailableError(UNAVAILABLE);
  }
  if (response === null) {
    throw new BackendApiError("Not authenticated", 401);
  }
  if (!response.ok) {
    const detail = await readErrorDetail(response, "Failed to reach the Copilot");
    throw new BackendApiError(detail, response.status);
  }
  return (await response.json()) as CopilotAskResponse;
}
