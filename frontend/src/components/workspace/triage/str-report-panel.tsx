"use client";

import { useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth, useRole } from "@/lib/auth/auth-provider";
import { isAssignedToUser } from "@/lib/workspace/case-assignment";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { REPORT_TYPES, type ReportModel, type ReportTypeValue } from "@/lib/api/types";

const REPORT_TYPE_LABELS: Record<ReportTypeValue, string> = {
  STR: "Suspicious Transaction Report (STR)",
  SAR: "Suspicious Activity Report (SAR)",
};

/**
 * STR/SAR reporting panel — case narrative generation, editing, finalize,
 * submit, and PDF download (ROADMAP Phase 21). One combined panel, not
 * separate "narrative" and "decision completion" panels: the backend
 * already treats generate/edit/finalize/submit as one `Report` lifecycle
 * (`backend/api/routes/reports.py`, one `ReportModel`/one status machine),
 * so splitting it across two frontend panels would just be a UI seam over
 * a single backend concept.
 *
 * DELIBERATE ROADMAP DEVIATION (flagged per this phase's task brief, same
 * convention as Session 30/Phase 19's precedent in
 * `docs/FRONTEND_ROADMAP.md`): the original Phase 21 scope described a
 * narrative panel mounted *before* `DecisionPanel`. That no longer fits —
 * the backend gates report generation on `case.status === "CLOSED_TP"`
 * (409 otherwise, enforced for both roles), i.e. strictly *after* a
 * decision has already been made, not before. So this panel mounts
 * *after* `<DecisionPanel>` in `case-tab-content.tsx`, and is entirely
 * gated on that same status rather than being reachable pre-decision.
 *
 * Role/status gating (mirrors `decision-panel.tsx`'s own posture exactly):
 *   - Not `CLOSED_TP` yet: informational-only, no fetch triggered (there
 *     can be nothing to show — a report can't exist before this status).
 *   - `CLOSED_TP` but this case isn't assigned to the current Investigator
 *     (and they're not Admin/Compliance): same read-only message
 *     `DecisionPanel` shows, since `require_case_access` gates every
 *     reports route the identical way.
 *   - `CLOSED_TP` and accessible: generate/list/edit available to the
 *     assigned Investigator or Admin/Compliance; Finalize/Submit
 *     controls only ever RENDER for Admin/Compliance (backstopped by the
 *     real 403, never relied on as the primary UX).
 *
 * "Most recent report" (judgment call, documented here since `ReportModel`
 * has no `generated_at`/timestamp field to sort by): the LAST element of
 * `GET /cases/{case_id}/reports`'s array is treated as current, since
 * `ReportRepository.list_for_case` has no explicit `ORDER BY` — this
 * relies on SQLite's own insertion-order-preserving scan behavior for an
 * unindexed query, not a documented ordering guarantee. A freshly
 * generated/edited/finalized/submitted report from THIS session always
 * overrides the fetched list via local `override` state regardless, so
 * this ordering assumption only matters for what's shown on first load of
 * an already-multi-report case — flagged as a known limitation, not
 * fixed here (would need a real `generated_at` on the response model,
 * out of this frontend-only phase's scope).
 */
export function StrReportPanel({ caseId }: { caseId: string }) {
  const role = useRole();
  const isAdmin = role === "ADMIN_COMPLIANCE";
  const { user } = useAuth();

  const summary = useCaseTabStore((state) => state.tabState[caseId]?.summary);
  const status = summary?.status ?? "";
  const isClosedTp = status === "CLOSED_TP";
  const isReadOnly = !isAdmin && summary != null && !isAssignedToUser(summary, user?.user_id);
  const canAct = isClosedTp && !isReadOnly;

  const listUrl = canAct ? `/api/cases/${encodeURIComponent(caseId)}/reports` : null;
  const { data, loading, error, refetch } = useTriageFetch<ReportModel[]>(listUrl);

  const [override, setOverride] = useState<ReportModel | null>(null);
  const fetchedCurrent = data && data.length > 0 ? data[data.length - 1] : null;
  const current = override ?? fetchedCurrent;
  const history = (data ?? []).filter((r) => r.report_id !== current?.report_id);

  const [reportType, setReportType] = useState<ReportTypeValue>("STR");
  const [generating, setGenerating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [narrativeDraft, setNarrativeDraft] = useState(current?.narrative ?? "");
  const [lastReportId, setLastReportId] = useState<string | null>(current?.report_id ?? null);
  if (current && current.report_id !== lastReportId) {
    setLastReportId(current.report_id);
    setNarrativeDraft(current.narrative ?? "");
  }
  const [saving, setSaving] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [fiuReference, setFiuReference] = useState("");

  async function post(path: string, body?: unknown): Promise<ReportModel> {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
    const responseBody = await res.json();
    if (!res.ok) {
      // Distinct plain-language framing for the two documented LLM-failure
      // statuses, rather than a generic message — an investigator hitting
      // 503 needs "try again later," not "something went wrong."
      if (res.status === 503) {
        throw new Error("The AI narrative service is temporarily unavailable. Try again shortly.");
      }
      if (res.status === 502) {
        throw new Error("The AI narrative could not be generated for this case. Try again.");
      }
      throw new Error(typeof responseBody.detail === "string" ? responseBody.detail : "Request failed");
    }
    return responseBody as ReportModel;
  }

  async function handleGenerate() {
    setGenerating(true);
    setActionError(null);
    try {
      const result = await post(`/api/cases/${encodeURIComponent(caseId)}/reports`, {
        type: reportType,
      });
      setOverride(result);
      refetch();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to generate report");
    } finally {
      setGenerating(false);
    }
  }

  async function handleSaveNarrative() {
    if (!current) return;
    setSaving(true);
    setActionError(null);
    try {
      const res = await fetch(`/api/reports/${encodeURIComponent(current.report_id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ narrative: narrativeDraft }),
      });
      const responseBody = await res.json();
      if (!res.ok) {
        throw new Error(
          typeof responseBody.detail === "string" ? responseBody.detail : "Failed to save narrative",
        );
      }
      setOverride(responseBody as ReportModel);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to save narrative");
    } finally {
      setSaving(false);
    }
  }

  async function handleFinalize() {
    if (!current) return;
    setFinalizing(true);
    setActionError(null);
    try {
      const result = await post(`/api/reports/${encodeURIComponent(current.report_id)}/finalize`);
      setOverride(result);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to finalize report");
    } finally {
      setFinalizing(false);
    }
  }

  async function handleSubmit() {
    if (!current) return;
    const trimmed = fiuReference.trim();
    if (!trimmed) {
      setActionError("An FIU-IND reference is required to submit.");
      return;
    }
    setSubmitting(true);
    setActionError(null);
    try {
      const result = await post(`/api/reports/${encodeURIComponent(current.report_id)}/submit`, {
        fiu_reference: trimmed,
      });
      setOverride(result);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to submit report");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>STR / SAR Reporting</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {!isClosedTp ? (
          <p className="text-muted-foreground text-sm">
            Available once this case is closed as a confirmed true positive (Close — True
            Positive). Reporting cannot begin before a final decision is recorded.
          </p>
        ) : isReadOnly ? (
          <p className="text-muted-foreground text-sm">
            This case isn&apos;t assigned to you — you&apos;re viewing it read-only.
          </p>
        ) : (
          <>
            {loading && <p className="text-muted-foreground text-sm">Loading reports…</p>}
            {!loading && error && (
              <Alert variant="destructive">
                <AlertTitle>Failed to load reports</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {!loading && !error && (
              <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-end gap-2">
                  <div className="flex flex-col gap-1.5">
                    <Label className="text-muted-foreground text-xs font-normal">Report type</Label>
                    <Select
                      value={reportType}
                      onValueChange={(value) => setReportType(value as ReportTypeValue)}
                    >
                      <SelectTrigger size="sm" className="w-64">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {REPORT_TYPES.map((t) => (
                          <SelectItem key={t} value={t}>
                            {REPORT_TYPE_LABELS[t]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button onClick={() => void handleGenerate()} disabled={generating}>
                    {generating
                      ? "Generating…"
                      : current
                        ? "Generate another report"
                        : "Generate report"}
                  </Button>
                </div>

                {actionError && (
                  <Alert variant="destructive">
                    <AlertTitle>Action failed</AlertTitle>
                    <AlertDescription>{actionError}</AlertDescription>
                  </Alert>
                )}

                {!current && (
                  <p className="text-muted-foreground text-sm">
                    No STR/SAR generated yet for this case.
                  </p>
                )}

                {current && (
                  <div className="flex flex-col gap-3 rounded-lg border p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="border-primary/40 bg-primary/5 text-primary">
                        AI-Generated Draft
                      </Badge>
                      <Badge variant="outline">{current.type}</Badge>
                      <Badge variant="outline">{current.status}</Badge>
                      <span className="text-muted-foreground text-xs">{current.report_id}</span>
                    </div>

                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor={`str-narrative-${current.report_id}`}>Narrative</Label>
                      <textarea
                        id={`str-narrative-${current.report_id}`}
                        value={narrativeDraft}
                        onChange={(e) => setNarrativeDraft(e.target.value)}
                        readOnly={current.status !== "DRAFT"}
                        className={
                          "border-input min-h-40 rounded-lg border bg-transparent p-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50" +
                          (current.status !== "DRAFT" ? " opacity-60" : "")
                        }
                      />
                      {current.status === "DRAFT" && (
                        <div>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => void handleSaveNarrative()}
                            disabled={saving || narrativeDraft.trim() === (current.narrative ?? "")}
                          >
                            {saving ? "Saving…" : "Save narrative"}
                          </Button>
                        </div>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-2">
                      {current.has_pdf && (
                        <Button
                          variant="outline"
                          size="sm"
                          render={<a href={`/api/reports/${encodeURIComponent(current.report_id)}/pdf`} />}
                        >
                          Download PDF
                        </Button>
                      )}

                      {/* Finalize/Submit controls only ever render for Admin/
                          Compliance — never shown to an Investigator, backstopped
                          by the real 403 but not relied on as the primary UX. */}
                      {isAdmin && current.status === "DRAFT" && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void handleFinalize()}
                          disabled={finalizing}
                        >
                          {finalizing ? "Finalizing…" : "Finalize"}
                        </Button>
                      )}
                      {isAdmin && current.status === "FINALIZED" && (
                        <>
                          <Input
                            className="w-48"
                            placeholder="FIU-IND reference"
                            value={fiuReference}
                            onChange={(e) => setFiuReference(e.target.value)}
                          />
                          <Button
                            size="sm"
                            onClick={() => void handleSubmit()}
                            disabled={submitting}
                          >
                            {submitting ? "Submitting…" : "Submit to FIU-IND"}
                          </Button>
                        </>
                      )}
                      {current.status === "SUBMITTED" && current.fiu_reference && (
                        <span className="text-muted-foreground text-xs">
                          Filed — FIU-IND reference {current.fiu_reference}
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {history.length > 0 && (
                  <details className="text-xs">
                    <summary className="text-muted-foreground cursor-pointer select-none">
                      {history.length} earlier report{history.length === 1 ? "" : "s"} on this case
                    </summary>
                    <div className="mt-2 flex flex-col gap-1">
                      {history.map((r) => (
                        <div key={r.report_id} className="flex items-center gap-2 rounded-lg border p-1.5">
                          <span className="font-medium">{r.report_id}</span>
                          <Badge variant="outline">{r.type}</Badge>
                          <Badge variant="outline">{r.status}</Badge>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
