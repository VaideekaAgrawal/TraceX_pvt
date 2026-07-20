"use client";

import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { ChallengeResponse, RecommendationsResponse } from "@/lib/api/types";

// Mirrors `orchestration.recommendation.engine.MAX_CHALLENGE_CHARS` (=1000)
// server-side — a client-side max-length hint only, the backend enforces
// the real limit via `ChallengeRequest.question`'s `max_length`.
const MAX_CHALLENGE_CHARS = 1000;

interface ChallengeEntry {
  question: string;
  answer: string;
  answered: boolean;
}

/**
 * "Recommendations" tab inside the floating AI widget
 * (`backend/api/routes/recommendations.py`, ROADMAP Phase 9 backend /
 * Phase 19 frontend). Real, functional — unlike the "Copilot" tab beside
 * it. `POST .../recommendations` is a genuine, billed LLM call, so it only
 * ever fires from the explicit "Generate recommendations" button click
 * below, never on mount/scope-change (matches this codebase's other AI
 * panels' `useTriageFetch`-on-mount convention being deliberately NOT used
 * here).
 *
 * `canAct` mirrors `decision-panel.tsx`'s own `assigned_to` check — both
 * routes this panel calls are `require_case_access` (assignment-gated), not
 * the read-only dependency the rest of L1/L2's GETs use, so a case open
 * read-only (not assigned to the current Investigator) would otherwise hit
 * a raw 403 the moment "Generate" was clicked. The button is disabled with
 * an explanatory message instead.
 *
 * 503 (LLM gateway unconfigured) and 502 (model produced no usable
 * structured output) both surface via the same plain destructive-text
 * error treatment `evidence-panel.tsx`/`decision-panel.tsx` already use for
 * a failed POST — the backend's own message text already reads as a clear,
 * honest "not available" statement for the 503 case (`orchestration.
 * gateway._NOT_CONFIGURED_MESSAGE`), so no separate special-casing is
 * needed here.
 *
 * Deliberately does NOT reuse the shared `AiGeneratedBanner` component —
 * that component's contract is `{model, generatedAt, cached}`, none of
 * which `RecommendationsResponse` actually returns (unlike every other AI
 * panel in this app, which is a per-account/per-alert cached explanation
 * with those exact fields). Fabricating a plausible-looking model name or
 * timestamp to fit that component's props would misrepresent what the
 * backend actually told the frontend — this panel instead renders its own
 * small "AI-Generated" badge using the fields the response really has
 * (`iterations`, `latency_ms`).
 */
export function RecommendationsPanel({
  caseId,
  canAct,
}: {
  caseId: string | null;
  canAct: boolean;
}) {
  const [result, setResult] = useState<RecommendationsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRejected, setShowRejected] = useState(false);

  const [question, setQuestion] = useState("");
  const [challenges, setChallenges] = useState<ChallengeEntry[]>([]);
  const [challengeSubmitting, setChallengeSubmitting] = useState(false);
  const [challengeError, setChallengeError] = useState<string | null>(null);

  async function handleGenerate() {
    if (!caseId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/recommendations`, {
        method: "POST",
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(
          typeof body.detail === "string" ? body.detail : "Failed to generate recommendations",
        );
      }
      setResult(body as RecommendationsResponse);
      setShowRejected(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate recommendations");
    } finally {
      setLoading(false);
    }
  }

  async function handleChallenge(e: FormEvent) {
    e.preventDefault();
    const trimmed = question.trim();
    if (!caseId || !trimmed) return;
    setChallengeSubmitting(true);
    setChallengeError(null);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/recommendations/challenge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to submit challenge");
      }
      const response = body as ChallengeResponse;
      setChallenges((prev) => [
        ...prev,
        {
          question: trimmed,
          answer: response.answered
            ? response.narrative
            : (response.rejected_reason ?? "The model could not produce a grounded answer to this question."),
          answered: response.answered,
        },
      ]);
      setQuestion("");
    } catch (err) {
      setChallengeError(err instanceof Error ? err.message : "Failed to submit challenge");
    } finally {
      setChallengeSubmitting(false);
    }
  }

  if (!caseId) {
    return (
      <p className="text-muted-foreground text-sm">
        No case open — open a case to see recommendations.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-muted-foreground text-xs">
        Generates ranked, evidence-grounded next-step recommendations for this case — a real model
        call, not cached or automatic.
      </p>

      <Button size="sm" onClick={() => void handleGenerate()} disabled={!canAct || loading}>
        {loading ? "Generating…" : result ? "Regenerate recommendations" : "Generate recommendations"}
      </Button>
      {!canAct && (
        <p className="text-muted-foreground text-xs">
          This case isn&apos;t assigned to you — recommendations can only be generated for a case
          you&apos;re actively working.
        </p>
      )}
      {error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}

      {result && (
        <div className="flex flex-col gap-3 border-t pt-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline" className="border-primary/40 bg-primary/5 text-primary">
              AI-Generated
            </Badge>
            <span>
              {result.iterations} reasoning iteration{result.iterations === 1 ? "" : "s"} ·{" "}
              {result.latency_ms}ms
            </span>
          </div>

          {result.recommendations.length === 0 && (
            <p className="text-muted-foreground text-sm">
              No recommendations were produced for this case.
            </p>
          )}

          {result.recommendations.map((rec) => (
            <div key={rec.action_id} className="rounded-lg border p-2 text-sm">
              <div className="flex items-start justify-between gap-2">
                <p className="font-medium">{rec.title}</p>
                <Badge variant="outline" className="shrink-0 text-[10px]">
                  {Math.round(rec.confidence * 100)}% confidence
                </Badge>
              </div>
              <p className="text-muted-foreground mt-1 text-xs">{rec.description}</p>
              <p className="mt-1.5 text-xs leading-relaxed">{rec.narrative}</p>

              {rec.typologies.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {rec.typologies.map((t) => (
                    <Badge key={t} variant="outline" className="text-[10px]">
                      {t}
                    </Badge>
                  ))}
                </div>
              )}

              <p className="text-muted-foreground mt-2 text-[11px]">
                FATF: {rec.regulatory_anchor.fatf} · India: {rec.regulatory_anchor.india}
              </p>

              {rec.cited_fact_keys.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {rec.cited_fact_keys.map((k) => (
                    <Badge
                      key={k}
                      variant="outline"
                      className="text-muted-foreground text-[10px] font-normal"
                    >
                      {k}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          ))}

          {result.rejected.length > 0 && (
            <div className="border-t pt-2">
              <button
                type="button"
                className="text-muted-foreground text-xs underline"
                onClick={() => setShowRejected((s) => !s)}
              >
                {showRejected ? "Hide" : "Show"} {result.rejected.length} filtered candidate
                {result.rejected.length === 1 ? "" : "s"}
              </button>
              {showRejected && (
                <div className="mt-2 flex flex-col gap-1.5">
                  {result.rejected.map((r) => (
                    <p key={r.action_id} className="text-muted-foreground text-xs">
                      <span className="font-medium">{r.action_id}:</span> {r.reason}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="border-t pt-2">
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">Ask a follow-up</p>

            {challenges.length > 0 && (
              <div className="mb-2 flex flex-col gap-2">
                {challenges.map((c, i) => (
                  <div key={i} className="flex flex-col gap-1 rounded-lg border p-2">
                    <p className="text-xs font-medium">You: {c.question}</p>
                    <p className={cn("text-xs leading-relaxed", !c.answered && "text-muted-foreground italic")}>
                      {c.answer}
                    </p>
                  </div>
                ))}
              </div>
            )}

            <form onSubmit={handleChallenge} className="flex gap-2">
              <Input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={MAX_CHALLENGE_CHARS}
                placeholder="Challenge a recommendation…"
                disabled={!canAct}
                className="h-8 flex-1 text-xs"
              />
              <Button type="submit" size="sm" disabled={!canAct || !question.trim() || challengeSubmitting}>
                {challengeSubmitting ? "…" : "Ask"}
              </Button>
            </form>
            {challengeError && (
              <p className="text-destructive mt-1 text-xs" role="alert">
                {challengeError}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
