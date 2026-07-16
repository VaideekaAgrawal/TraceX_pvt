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
  CustomerSnapshotResponse,
  DecisionRequest,
  DecisionResponse,
  ExplanationResponse,
  GeoRiskResponse,
  MoneyFlowResponse,
  NetworkRiskResponse,
  NoteCreateRequest,
  NoteItem,
  PreviousAlertsResponse,
  SimilarCasesResponse,
  TransactionPurposeResponse,
  TransactionSummaryResponse,
} from "@/lib/api/types";

const UNAVAILABLE = "Unable to reach the case service";

function toQueryString(params: Record<string, unknown>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    qs.set(key, String(value));
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
