"use client";

import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { CopilotAskResponse } from "@/lib/api/types";

// Mirrors `orchestration.copilot.engine.MAX_QUESTION_CHARS` (=1000)
// server-side — a client-side max-length hint only, the backend enforces
// the real limit via `AskRequest.question`'s `max_length`.
const MAX_QUESTION_CHARS = 1000;

interface ChatEntry {
  question: string;
  answer: string;
  answered: boolean;
  toolsUsed: string[];
}

/**
 * "Copilot" tab inside the floating AI widget (`backend/api/routes/
 * copilot.py`, ROADMAP Phase 10 backend / Phase 20 frontend) — replaces
 * `copilot-placeholder.tsx` now that the backend agent exists. Cross-case
 * by design (owner decision, 2026-07-20): no separate embedded-in-workspace
 * panel or standalone My Center widget — this same tab, scoped to *the
 * caller's own cases* server-side, answers both case-drill-down questions
 * ("summarise case CASE-123's money flow") and cross-case digest questions
 * ("what's changed since I last logged in", "which of my cases is highest
 * risk") without needing a case tab open, unlike `RecommendationsPanel`
 * (which is genuinely case-scoped and requires `caseId`).
 *
 * History is plain `useState`, scoped to this component instance only — not
 * Zustand, not `localStorage`. This is deliberate, not an oversight: Phase
 * 10 decision 9 re-hydrates a `customer_id` to a display name only for the
 * single response the model produced (the persisted `ai_interactions` row
 * keeps the id, never the name) — the frontend holding that rendered name
 * in anything beyond in-memory render state for this mounted instance would
 * quietly defeat that guarantee. A page reload/tab close clears it, same as
 * `RecommendationsPanel`'s own challenge history.
 *
 * No note-reading surface here (and never add one): decision 10 keeps
 * `notes.body` out of every prompt by construction — the Copilot can *write*
 * a note (surfaced here only as a `write_case_note` entry in `tools_used`,
 * never the note body itself, which this response doesn't return) but there
 * is no tool that reads one back.
 */
export function CopilotPanel() {
  const [history, setHistory] = useState<ChatEntry[]>([]);
  const [question, setQuestion] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/copilot/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to ask the Copilot");
      }
      const response = body as CopilotAskResponse;
      setHistory((prev) => [
        ...prev,
        {
          question: trimmed,
          answer: response.answered
            ? response.answer
            : (response.rejected_reason ?? "The Copilot could not produce a grounded answer to this question."),
          answered: response.answered,
          toolsUsed: response.tools_used ?? [],
        },
      ]);
      setQuestion("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to ask the Copilot");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <p className="text-muted-foreground text-xs">
        Ask about any of your own cases — a real model call, grounded and cited to tool facts. Not
        cached, not automatic.
      </p>

      {history.length === 0 && !submitting && (
        <p className="text-muted-foreground text-xs italic">
          Try &ldquo;what&apos;s changed since I last logged in?&rdquo; or &ldquo;which of my cases is
          highest risk?&rdquo;
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {history.length > 0 && (
          <div className="flex flex-col gap-2">
            {history.map((entry, i) => (
              <div key={i} className="flex flex-col gap-1 rounded-lg border p-2">
                <p className="text-xs font-medium">You: {entry.question}</p>
                <p
                  className={cn(
                    "text-xs leading-relaxed",
                    !entry.answered && "text-muted-foreground italic",
                  )}
                >
                  {entry.answer}
                </p>
                {entry.answered && (
                  <div className="mt-0.5 flex flex-wrap items-center gap-1">
                    <Badge variant="outline" className="border-primary/40 bg-primary/5 text-[9px] text-primary">
                      AI-Generated
                    </Badge>
                    {entry.toolsUsed.map((tool) => (
                      <Badge key={tool} variant="outline" className="text-muted-foreground text-[9px] font-normal">
                        {tool}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}

      <form onSubmit={handleSubmit} className="flex gap-2 border-t pt-2">
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={MAX_QUESTION_CHARS}
          placeholder="Ask the Copilot…"
          disabled={submitting}
          className="h-8 flex-1 text-xs"
        />
        <Button type="submit" size="sm" disabled={!question.trim() || submitting}>
          {submitting ? "…" : "Ask"}
        </Button>
      </form>
    </div>
  );
}
