"use client";

import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AiGeneratedBanner } from "@/components/workspace/ai-generated-banner";
import { detectionTypeLabel, severityBadgeClassName } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { AlertSummaryItem, PatternExplanationResponse } from "@/lib/api/types";

/**
 * L2 §6 — Pattern Explanation, `GET .../alerts/{alert_id}/pattern-
 * explanation` (ROADMAP Phase 18). Per-ALERT, not per-case/per-account — a
 * case can carry multiple alerts (`AlertSummarySection` above already
 * fetches the full list via `GET .../summary/alerts`), so this panel owns
 * its own small alert selector rather than assuming one alert per case.
 * Defaults to the highest-`risk_score` alert (a judgment call — the
 * backend response has no "primary alert" concept of its own to default
 * to instead).
 *
 * Same AI-panel treatment as `triage/ai-panel.tsx`'s L1 account
 * explanation: labeled `AiGeneratedBanner` (now a shared component, see
 * that file), cached indicator, facts-only prose, regenerate button.
 * `rule_anchors` is rendered as plain-language chips (detection type +
 * triggering rule ids) — a structured pointer back to what triggered the
 * alert, not a raw ML score — matching this codebase's "translate to
 * plain-language, evidence-backed statements" invariant.
 */
export function PatternExplanationSection({ caseId }: { caseId: string }) {
  const { data: alerts, loading: alertsLoading, error: alertsError } = useTriageFetch<
    AlertSummaryItem[]
  >(`/api/cases/${encodeURIComponent(caseId)}/summary/alerts`);

  const sortedAlerts = useMemo(
    () => [...(alerts ?? [])].sort((a, b) => b.risk_score - a.risk_score),
    [alerts],
  );

  const [selectedAlertId, setSelectedAlertId] = useState<string | null>(null);

  // Defaults to the highest-risk alert exactly once, when the alert list
  // first arrives — never overrides a subsequent manual selection (same
  // "default once, don't clobber a user choice" posture as
  // `investigation-graph.tsx`'s filter state). Adjusted during render
  // (React's own documented pattern, https://react.dev/learn/you-might-not-need-an-effect)
  // rather than in an Effect — `eslint-plugin-react-hooks`'s
  // `set-state-in-effect` rule flags a direct, unconditional setState call
  // in an effect body; `alerts !== lastAlerts` guards this to run only
  // once per genuinely new fetch result, not every render.
  const [lastAlerts, setLastAlerts] = useState(alerts);
  if (alerts !== lastAlerts) {
    setLastAlerts(alerts);
    if (selectedAlertId === null && sortedAlerts.length > 0) {
      setSelectedAlertId(sortedAlerts[0].alert_id);
    }
  }

  return (
    <TriageSection
      title="Pattern Explanation"
      description="AI-generated explanation of the detected typology for a selected alert, grounded only in that alert's own persisted facts."
      loading={alertsLoading}
      error={alertsError}
      isEmpty={!!alerts && alerts.length === 0}
      emptyText="No alerts recorded on this case to explain."
    >
      {sortedAlerts.length > 0 && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground text-xs font-normal">Alert</span>
            <Select
              value={selectedAlertId ?? undefined}
              onValueChange={(value) => setSelectedAlertId(String(value))}
            >
              <SelectTrigger size="sm" className="w-64" aria-label="Alert">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {sortedAlerts.map((alert) => (
                  <SelectItem key={alert.alert_id} value={alert.alert_id}>
                    {alert.alert_id} — {detectionTypeLabel(alert.detection_type)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedAlertId && (
              <Badge
                variant="outline"
                className={severityBadgeClassName(
                  sortedAlerts.find((a) => a.alert_id === selectedAlertId)?.severity ?? "",
                )}
              >
                {sortedAlerts.find((a) => a.alert_id === selectedAlertId)?.severity}
              </Badge>
            )}
          </div>

          {selectedAlertId && <PatternExplanationBody caseId={caseId} alertId={selectedAlertId} />}
        </div>
      )}
    </TriageSection>
  );
}

function PatternExplanationBody({ caseId, alertId }: { caseId: string; alertId: string }) {
  const [regenNonce, setRegenNonce] = useState(0);
  const url =
    `/api/cases/${encodeURIComponent(caseId)}/alerts/${encodeURIComponent(alertId)}/pattern-explanation` +
    (regenNonce > 0 ? `?force=true&_r=${regenNonce}` : "");
  const { data, loading, error } = useTriageFetch<PatternExplanationResponse>(url);

  return (
    <div className="flex flex-col gap-2 border-t pt-3">
      {loading && <p className="text-muted-foreground text-sm">Generating explanation…</p>}
      {!loading && error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}
      {!loading && !error && data && (
        <>
          <AiGeneratedBanner model={data.model} generatedAt={data.generated_at} cached={data.cached} />
          <p className="text-sm leading-relaxed">{data.explanation}</p>

          {data.rule_anchors && (
            <div className="flex flex-wrap items-center gap-1.5">
              {data.rule_anchors.detection_type && (
                <Badge variant="outline">
                  Pattern: {detectionTypeLabel(data.rule_anchors.detection_type)}
                </Badge>
              )}
              {(data.rule_anchors.rule_ids ?? []).map((ruleId) => (
                <Badge key={ruleId} variant="outline">
                  Rule: {ruleId}
                </Badge>
              ))}
              {(!data.rule_anchors.rule_ids || data.rule_anchors.rule_ids.length === 0) && (
                <Badge variant="outline">Composite ML scoring (no rule-engine match)</Badge>
              )}
            </div>
          )}

          <div>
            <Button variant="outline" size="sm" onClick={() => setRegenNonce((n) => n + 1)} disabled={loading}>
              <RefreshCw />
              Regenerate
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
