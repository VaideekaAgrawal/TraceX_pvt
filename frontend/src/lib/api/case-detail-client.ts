/**
 * Typed wrappers around the `/cases/{case_id}/...` L1 triage routes
 * (`backend/api/routes/cases.py`, plus `notes` from `backend/api/routes/l2.py`
 * — ROADMAP Phase 16). Server-only — called from
 * this app's own `/api/cases/[caseId]/...` Route Handlers, never directly
 * from a Client Component. Mirrors `alerts-client.ts`/`cases-client.ts`'s
 * exact conventions:
 *
 *   - Read (`GET`) functions return `null` for "not authenticated" (no
 *     cookie, or backend 401) via `parseAuthedJsonResponse`, throw
 *     `BackendApiError` for a real rejection (403 role/case-scope violation,
 *     404 case-scoped-account miss, 400 validation) with the real status
 *     preserved, and `BackendUnavailableError` for a genuine backend fault.
 *   - Write (`POST`) functions always throw on non-2xx (including "not
 *     authenticated" — there's no sensible `null` return for a write),
 *     same as `assignAlert`.
 */
import "server-only";

import { authedBackendFetch, BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { parseAuthedJsonResponse } from "@/lib/api/response-mapping";
import type {
  AlertSummaryItem,
  BehaviorAnalysisResponse,
  CaseListItem,
  ChallengeRequest,
  ChallengeResponse,
  CustomerProfileResponse,
  CustomerSnapshotResponse,
  DecisionRequest,
  DecisionResponse,
  EvidenceCreateRequest,
  EvidenceItem,
  ExplanationResponse,
  GeoRiskResponse,
  GraphExplanationResponse,
  GraphQueryParams,
  MoneyFlowResponse,
  NetworkRiskResponse,
  NHopGraphResponse,
  NoteCreateRequest,
  NoteItem,
  PatternExplanationResponse,
  PreviousAlertsResponse,
  RecommendationsResponse,
  RelationshipGraphResponse,
  SimilarCasesResponse,
  TimelineQueryParams,
  TimelineResponse,
  TransactionPurposeResponse,
  TransactionSearchParams,
  TransactionSearchResponse,
  TransactionSummaryResponse,
} from "@/lib/api/types";

const UNAVAILABLE = "Unable to reach the case service";

// `channels`/`roles` (L2 graph + transaction-search query params) are real
// arrays serialized as repeated query keys (`?channels=UPI&channels=NEFT`),
// matching FastAPI's `list[str]` `Query(...)` parsing server-side — same
// convention `audit-client.ts`'s `toQueryString` already established for
// `AuditLogParams.action`. Extended here (rather than duplicated) since this
// module now has its own array-valued params to serialize.
function toQueryString(params: Record<string, unknown>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) qs.append(key, String(item));
    } else {
      qs.set(key, String(value));
    }
  }
  return qs.toString();
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : fallback;
  } catch {
    return fallback;
  }
}

async function getJson<T>(path: string): Promise<T | null> {
  let response: Response | null;
  try {
    response = await authedBackendFetch(path);
  } catch {
    throw new BackendUnavailableError(UNAVAILABLE);
  }
  return parseAuthedJsonResponse<T>(response, UNAVAILABLE);
}

async function postJson<T>(path: string, body: unknown, fallback: string): Promise<T> {
  let response: Response | null;
  try {
    response = await authedBackendFetch(path, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw new BackendUnavailableError(UNAVAILABLE);
  }
  if (response === null) {
    throw new BackendApiError("Not authenticated", 401);
  }
  if (!response.ok) {
    const detail = await readErrorDetail(response, fallback);
    throw new BackendApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

/** Same contract as `postJson` above, for the one `PATCH` route this module
 * calls (`.../evidence/{evidence_id}/pin`) — no request body. */
async function patchJson<T>(path: string, fallback: string): Promise<T> {
  let response: Response | null;
  try {
    response = await authedBackendFetch(path, { method: "PATCH" });
  } catch {
    throw new BackendUnavailableError(UNAVAILABLE);
  }
  if (response === null) {
    throw new BackendApiError("Not authenticated", 401);
  }
  if (!response.ok) {
    const detail = await readErrorDetail(response, fallback);
    throw new BackendApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

/**
 * Single-case lookup (`GET /cases/{case_id}`) — reachable for ANY case by
 * ANY authenticated user (`require_case_read_access`, not the
 * assignment-gated `require_case_access`), so this is safe to call for a
 * case the current user doesn't own, e.g. opening a Similar Case / Previous
 * Investigation History row as a real tab (`similar-cases.tsx`/
 * `previous-alerts.tsx`) or `workspace-shell.tsx`'s `?case=` deep link.
 * Returns the same `CaseListItem` shape `GET /cases` returns per row, so
 * callers can feed the result straight into `useCaseTabStore`'s `openCase`.
 */
export async function getCase(caseId: string): Promise<CaseListItem | null> {
  return getJson<CaseListItem>(`/cases/${encodeURIComponent(caseId)}`);
}

export async function getAlertSummary(caseId: string): Promise<AlertSummaryItem[] | null> {
  return getJson<AlertSummaryItem[]>(`/cases/${encodeURIComponent(caseId)}/summary/alerts`);
}

export async function getAccountExplanation(
  caseId: string,
  accountId: string,
  force = false,
): Promise<ExplanationResponse | null> {
  const qs = toQueryString({ force });
  return getJson<ExplanationResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/explanation${qs ? `?${qs}` : ""}`,
  );
}

export async function getCustomerSnapshot(
  caseId: string,
  accountId: string,
): Promise<CustomerSnapshotResponse | null> {
  return getJson<CustomerSnapshotResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/customer-snapshot`,
  );
}

export async function getGeoRisk(
  caseId: string,
  accountId: string,
): Promise<GeoRiskResponse | null> {
  return getJson<GeoRiskResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/geo-risk`,
  );
}

export async function getMoneyFlow(
  caseId: string,
  accountId: string,
): Promise<MoneyFlowResponse | null> {
  return getJson<MoneyFlowResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/money-flow`,
  );
}

export async function getTransactionSummary(
  caseId: string,
  accountId: string,
  params: { start?: string; end?: string } = {},
): Promise<TransactionSummaryResponse | null> {
  const qs = toQueryString(params);
  return getJson<TransactionSummaryResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/transaction-summary${qs ? `?${qs}` : ""}`,
  );
}

export async function getTransactionPurpose(
  caseId: string,
  accountId: string,
): Promise<TransactionPurposeResponse | null> {
  return getJson<TransactionPurposeResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/transaction-purpose`,
  );
}

export async function getPreviousAlerts(
  caseId: string,
  accountId: string,
): Promise<PreviousAlertsResponse | null> {
  return getJson<PreviousAlertsResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/previous-alerts`,
  );
}

export async function getNetworkRisk(caseId: string): Promise<NetworkRiskResponse | null> {
  return getJson<NetworkRiskResponse>(`/cases/${encodeURIComponent(caseId)}/network-risk`);
}

/** Always a write (recomputes + commits server-side) — throws, never `null`. */
export async function recomputeNetworkRisk(caseId: string): Promise<NetworkRiskResponse> {
  return postJson<NetworkRiskResponse>(
    `/cases/${encodeURIComponent(caseId)}/network-risk/recompute`,
    {},
    "Failed to recompute network risk",
  );
}

export async function getSimilarCases(
  caseId: string,
  topK = 3,
): Promise<SimilarCasesResponse | null> {
  const qs = toQueryString({ top_k: topK });
  return getJson<SimilarCasesResponse>(
    `/cases/${encodeURIComponent(caseId)}/similar-cases${qs ? `?${qs}` : ""}`,
  );
}

export async function listNotes(caseId: string): Promise<NoteItem[] | null> {
  return getJson<NoteItem[]>(`/cases/${encodeURIComponent(caseId)}/notes`);
}

export async function createNote(caseId: string, body: NoteCreateRequest): Promise<NoteItem> {
  return postJson<NoteItem>(`/cases/${encodeURIComponent(caseId)}/notes`, body, "Failed to save note");
}

export async function postDecision(
  caseId: string,
  body: DecisionRequest,
): Promise<DecisionResponse> {
  return postJson<DecisionResponse>(
    `/cases/${encodeURIComponent(caseId)}/decision`,
    body,
    "Failed to submit decision",
  );
}

/** `POST /cases/{case_id}/start` — the `ASSIGNED -> IN_PROGRESS` step, no
 * request body. Assignment-gated (`require_case_access`) server-side, same
 * as `postDecision` — always throws on non-2xx (including a 409 for an
 * illegal transition, e.g. the case has already moved past `ASSIGNED`),
 * never `null`. Callers that treat this as best-effort background UX
 * polish (`case-tab-content.tsx`'s auto-start effect) catch that
 * themselves rather than this function swallowing it. */
export async function startInvestigation(caseId: string): Promise<CaseListItem> {
  return postJson<CaseListItem>(
    `/cases/${encodeURIComponent(caseId)}/start`,
    undefined,
    "Failed to start investigation",
  );
}

// ── L2 Deep Investigation (`backend/api/routes/l2.py`, ROADMAP Phase 17) ──

export async function getAccountGraph(
  caseId: string,
  accountId: string,
  params: GraphQueryParams = {},
): Promise<NHopGraphResponse | null> {
  const qs = toQueryString(params as Record<string, unknown>);
  return getJson<NHopGraphResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/graph${qs ? `?${qs}` : ""}`,
  );
}

export async function getAccountTimeline(
  caseId: string,
  accountId: string,
  params: TimelineQueryParams = {},
): Promise<TimelineResponse | null> {
  const qs = toQueryString(params as Record<string, unknown>);
  return getJson<TimelineResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/timeline${qs ? `?${qs}` : ""}`,
  );
}

export async function searchCaseTransactions(
  caseId: string,
  params: TransactionSearchParams = {},
): Promise<TransactionSearchResponse | null> {
  const qs = toQueryString(params as Record<string, unknown>);
  return getJson<TransactionSearchResponse>(
    `/cases/${encodeURIComponent(caseId)}/transactions/search${qs ? `?${qs}` : ""}`,
  );
}

export async function searchAccountTransactions(
  caseId: string,
  accountId: string,
  params: TransactionSearchParams = {},
): Promise<TransactionSearchResponse | null> {
  const qs = toQueryString(params as Record<string, unknown>);
  return getJson<TransactionSearchResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/transactions/search${qs ? `?${qs}` : ""}`,
  );
}

export async function getCustomerProfile(
  caseId: string,
  accountId: string,
): Promise<CustomerProfileResponse | null> {
  return getJson<CustomerProfileResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/profile`,
  );
}

export async function getAccountBehavior(
  caseId: string,
  accountId: string,
): Promise<BehaviorAnalysisResponse | null> {
  return getJson<BehaviorAnalysisResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/behavior`,
  );
}

// ── L2 Deep Investigation, part 2 (`backend/api/routes/l2.py`, ROADMAP
// Phase 18) — relationships, pattern explanation, evidence ────────────────

/** `GET .../graph-explanation` — AI narrative of the Investigation Graph
 * (`backend/api/routes/l2.py::get_graph_explanation`), identical shape/
 * `force` convention to `getAccountExplanation` above (`.../explanation`).
 * Scoped to `account_id` directly, one explanation per account per case —
 * unlike `getPatternExplanation` below, which is per-alert. */
export async function getGraphExplanation(
  caseId: string,
  accountId: string,
  force = false,
): Promise<GraphExplanationResponse | null> {
  const qs = toQueryString({ force });
  return getJson<GraphExplanationResponse>(
    `/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/graph-explanation${qs ? `?${qs}` : ""}`,
  );
}

export async function getCaseRelationships(
  caseId: string,
): Promise<RelationshipGraphResponse | null> {
  return getJson<RelationshipGraphResponse>(`/cases/${encodeURIComponent(caseId)}/relationships`);
}

export async function getPatternExplanation(
  caseId: string,
  alertId: string,
  force = false,
): Promise<PatternExplanationResponse | null> {
  const qs = toQueryString({ force });
  return getJson<PatternExplanationResponse>(
    `/cases/${encodeURIComponent(caseId)}/alerts/${encodeURIComponent(alertId)}/pattern-explanation${qs ? `?${qs}` : ""}`,
  );
}

export async function listEvidence(
  caseId: string,
  pinned?: boolean,
): Promise<EvidenceItem[] | null> {
  const qs = toQueryString({ pinned });
  return getJson<EvidenceItem[]>(`/cases/${encodeURIComponent(caseId)}/evidence${qs ? `?${qs}` : ""}`);
}

export async function createEvidence(
  caseId: string,
  body: EvidenceCreateRequest,
): Promise<EvidenceItem> {
  return postJson<EvidenceItem>(
    `/cases/${encodeURIComponent(caseId)}/evidence`,
    body,
    "Failed to save evidence",
  );
}

/** One-directional (`pinned` always ends up `true`) — matches
 * `EvidenceRepository.pin`'s own contract server-side; there is no
 * "unpin" route, so no such function is exposed here either. */
export async function pinEvidence(caseId: string, evidenceId: string): Promise<EvidenceItem> {
  return patchJson<EvidenceItem>(
    `/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}/pin`,
    "Failed to pin evidence",
  );
}

// ── AI Recommendations widget (`backend/api/routes/recommendations.py`,
// ROADMAP Phase 19) ────────────────────────────────────────────────────
//
// Both routes are `require_case_access` (assignment-gated) server-side, NOT
// the read-only dependency the rest of this module's GET functions use —
// this genuinely IS a write (a real, billed LLM call that persists an
// `ai_interactions` row), matching this module's own POST convention. Both
// always throw on non-2xx (403 for a case not assigned to the caller, 503
// if the LLM gateway is unconfigured, 502 if the model failed to produce
// valid structured output) — never `null`, same as `postDecision`.

/** `POST /cases/{case_id}/recommendations` — a real, billed LLM call, never
 * auto-fired. `ai-widget/recommendations-panel.tsx` only calls this from an
 * explicit "Generate" button click. */
export async function generateRecommendations(caseId: string): Promise<RecommendationsResponse> {
  return postJson<RecommendationsResponse>(
    `/cases/${encodeURIComponent(caseId)}/recommendations`,
    undefined,
    "Failed to generate recommendations",
  );
}

/** `POST /cases/{case_id}/recommendations/challenge` — cross-questions the
 * most recent generated recommendation set for this case; the engine
 * defends or concedes with grounded, cited facts appended to the same
 * audited interaction thread. */
export async function challengeRecommendation(
  caseId: string,
  body: ChallengeRequest,
): Promise<ChallengeResponse> {
  return postJson<ChallengeResponse>(
    `/cases/${encodeURIComponent(caseId)}/recommendations/challenge`,
    body,
    "Failed to submit challenge",
  );
}
