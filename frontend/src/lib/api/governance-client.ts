/**
 * Typed wrapper around `backend/api/routes/governance.py`'s `GET
 * /model-metrics` (ROADMAP Phase 12 backend / Phase 22 frontend, model
 * governance surfacing). Server-only — called from this app's own
 * `/api/model-metrics` Route Handler, never directly from a Client
 * Component. Mirrors `audit-client.ts`'s exact conventions.
 *
 * Admin/Compliance only server-side (403 for an Investigator) — the
 * frontend never even attempts this fetch for a non-admin (see
 * `model-governance-indicator.tsx`'s `useRole()` gate), but this client
 * still forwards a real 403 as-is if it's ever hit anyway, same as every
 * other client in this file's family.
 */
import "server-only";

import { authedBackendFetch } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { parseAuthedJsonResponse } from "@/lib/api/response-mapping";
import type { ModelMetricsResponse } from "@/lib/api/types";

export async function getModelMetrics(): Promise<ModelMetricsResponse | null> {
  let response: Response | null;
  try {
    response = await authedBackendFetch("/model-metrics");
  } catch {
    throw new BackendUnavailableError("Unable to reach the model governance service");
  }

  return parseAuthedJsonResponse<ModelMetricsResponse>(
    response,
    "Unable to reach the model governance service",
  );
}
