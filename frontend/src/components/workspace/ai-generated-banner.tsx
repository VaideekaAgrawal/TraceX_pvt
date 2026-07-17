"use client";

import { Badge } from "@/components/ui/badge";
import { formatDateTime } from "@/components/dashboard/format";

/**
 * Shared "AI-Generated" labeling chrome — factored out of
 * `triage/ai-panel.tsx` (ROADMAP Phase 16's L1 account explanation) when
 * `deep/pattern-explanation-panel.tsx` (ROADMAP Phase 18's per-alert
 * pattern explanation) needed the identical treatment: labeled badge,
 * model + timestamp, cached indicator. Every AI-generated panel in this
 * app must use this same banner rather than growing its own copy —
 * matches this codebase's "AI-generated content must read as
 * AI-generated" invariant (`CLAUDE.md`).
 */
export function AiGeneratedBanner({
  model,
  generatedAt,
  cached,
}: {
  model: string;
  generatedAt: string;
  cached: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <Badge variant="outline" className="border-primary/40 bg-primary/5 text-primary">
        AI-Generated
      </Badge>
      <span>
        {model} · {formatDateTime(generatedAt)}
        {cached ? " · cached" : ""}
      </span>
    </div>
  );
}
