/**
 * Typed wrappers around `backend/api/routes/reports.py` — STR/SAR
 * generation (ROADMAP Phase 11 backend / Phase 21 frontend). Server-only —
 * called from this app's own `/api/cases/[caseId]/reports` and
 * `/api/reports/[reportId]/...` Route Handlers, never directly from a
 * Client Component. Mirrors `case-detail-client.ts`'s exact conventions
 * (`getJson` returns `null` for "not authenticated", write functions
 * always throw on non-2xx).
 *
 * `fetchReportPdf` is the one exception to the "typed JSON" shape every
 * other function here has — the backend route it wraps returns raw PDF
 * bytes (`FileResponse`), not JSON, so it returns the raw `Response`
 * object and lets its Route Handler (`app/api/reports/[reportId]/pdf/
 * route.ts`) decide how to stream/forward it. This is the first binary
 * (non-JSON) backend route this codebase's BFF layer wraps.
 */
import "server-only";

import { authedBackendFetch, BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { parseAuthedJsonResponse } from "@/lib/api/response-mapping";
import type {
  EditNarrativeRequest,
  GenerateReportRequest,
  ReportModel,
  SubmitReportRequest,
} from "@/lib/api/types";

const UNAVAILABLE = "Unable to reach the reporting service";

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

async function patchJson<T>(path: string, body: unknown, fallback: string): Promise<T> {
  let response: Response | null;
  try {
    response = await authedBackendFetch(path, {
      method: "PATCH",
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

/**
 * `POST /cases/{case_id}/reports` — generate a DRAFT STR/SAR. A real,
 * billed LLM call (the grounded narrative), never auto-fired — only from
 * an explicit "Generate" click in `str-report-panel.tsx`. Throws
 * `BackendApiError` for the documented 409 (case not `CLOSED_TP`), 503
 * (LLM unconfigured), or 502 (narrative generation failed) — the panel
 * renders each distinctly rather than a generic error.
 */
export async function generateReport(
  caseId: string,
  body: GenerateReportRequest = {},
): Promise<ReportModel> {
  return postJson<ReportModel>(
    `/cases/${encodeURIComponent(caseId)}/reports`,
    body,
    "Failed to generate report",
  );
}

/**
 * `GET /cases/{case_id}/reports` — every report row for this case (a case
 * can accumulate more than one, e.g. a retried generation). Caller treats
 * the array's last element as "most recent" — see `str-report-panel.tsx`'s
 * docstring for why (no `generated_at` on `ReportModel` to sort by).
 */
export async function listReports(caseId: string): Promise<ReportModel[] | null> {
  return getJson<ReportModel[]>(`/cases/${encodeURIComponent(caseId)}/reports`);
}

export async function getReport(reportId: string): Promise<ReportModel | null> {
  return getJson<ReportModel>(`/reports/${encodeURIComponent(reportId)}`);
}

/** `PATCH /reports/{report_id}` — edit a DRAFT's narrative (409 if not DRAFT). */
export async function editReportNarrative(
  reportId: string,
  body: EditNarrativeRequest,
): Promise<ReportModel> {
  return patchJson<ReportModel>(
    `/reports/${encodeURIComponent(reportId)}`,
    body,
    "Failed to save narrative",
  );
}

/** `POST /reports/{report_id}/finalize` — DRAFT -> FINALIZED. Admin/
 * Compliance only server-side (403 otherwise); `str-report-panel.tsx`
 * doesn't render this control for a non-admin at all. */
export async function finalizeReport(reportId: string): Promise<ReportModel> {
  return postJson<ReportModel>(
    `/reports/${encodeURIComponent(reportId)}/finalize`,
    undefined,
    "Failed to finalize report",
  );
}

/** `POST /reports/{report_id}/submit` — FINALIZED -> SUBMITTED. Admin/
 * Compliance only server-side, same posture as `finalizeReport`. */
export async function submitReport(
  reportId: string,
  body: SubmitReportRequest,
): Promise<ReportModel> {
  return postJson<ReportModel>(
    `/reports/${encodeURIComponent(reportId)}/submit`,
    body,
    "Failed to submit report",
  );
}

/**
 * `GET /reports/{report_id}/pdf` — raw PDF bytes. Returns `null` for "not
 * authenticated" (no session cookie), otherwise the raw `Response` —
 * callers must check `.ok` themselves (a 404 here means "not generated
 * yet," not "unauthenticated"). See this module's docstring for why this
 * one function breaks from the "typed JSON" shape every other function
 * here has.
 */
export async function fetchReportPdf(reportId: string): Promise<Response | null> {
  try {
    return await authedBackendFetch(`/reports/${encodeURIComponent(reportId)}/pdf`);
  } catch {
    throw new BackendUnavailableError(UNAVAILABLE);
  }
}
