/**
 * "Copilot" tab inside the floating AI widget — explicitly a "Coming soon"
 * placeholder, NOT a chat interface with faked/mocked responses. Backend
 * Phase 10 (the Investigation Copilot — a genuine free-text conversational
 * agent over a case) does not exist yet, and this codebase's hard invariant
 * ("nothing in the UI ever presents a mocked/hardcoded value as real")
 * means the only acceptable treatment here is honest "not yet available"
 * copy — same pattern `deep/behavior-analysis.tsx` already uses for its
 * `deferred` fields, applied to a whole feature instead of a few fields.
 *
 * Also worth noting for whenever Phase 10 does ship: a free-text copilot
 * reading narration/notes/case content is a genuinely different AI-input
 * surface than the existing per-account explanation pattern (server-
 * injected facts, low temperature, no user-controlled free text reaching
 * the model) — it will need its own explicit guardrail design, not an
 * assumption that the existing pattern transfers (`CLAUDE.md`).
 */
export function CopilotPlaceholder() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
      <p className="text-sm font-medium">Investigation Copilot — coming soon</p>
      <p className="text-muted-foreground text-xs">
        A free-text conversational assistant over this case isn&apos;t built yet. This tab
        intentionally does not simulate one — no response shown here would be real.
      </p>
    </div>
  );
}
