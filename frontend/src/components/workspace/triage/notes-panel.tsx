"use client";

import { useEffect, useRef, useState } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/components/dashboard/format";
import { useCaseTabStore } from "@/lib/workspace/case-tab-store";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import type { NoteItem } from "@/lib/api/types";

const AUTOSAVE_DEBOUNCE_MS = 2000;

/**
 * L1 Triage §10 — Investigator Notes. `POST /cases/{case_id}/notes` on a
 * debounced pause — **no manual "Save" button**, per spec. The compose box
 * itself lives in the per-case Zustand store (`notesDraft`, same field
 * Phase 15's placeholder already exercised for tab-switch survival) so an
 * in-progress, not-yet-autosaved draft survives a tab switch; once a
 * debounce actually fires and the `POST` succeeds, the draft is cleared and
 * the new note is appended to the read-only list below — the draft box is
 * for composing the *next* note, not an editable view of a past one (notes
 * are append-only, matching the endpoint: no `PATCH`/edit route is wired
 * here even though `NoteRepository.update` exists server-side, since no
 * route exposes it).
 */
export function NotesPanel({ caseId }: { caseId: string }) {
  const { data: initialNotes, loading, error } = useTriageFetch<NoteItem[]>(
    `/api/cases/${encodeURIComponent(caseId)}/notes`,
  );
  // `notes` shown below = the fetched list + anything autosaved locally
  // this session — kept as two pieces rather than copying `initialNotes`
  // into local state via an effect (that copy-on-fetch pattern is exactly
  // what `eslint-plugin-react-hooks`'s `set-state-in-effect` rule flags;
  // deriving at render time needs no effect at all).
  const [appendedNotes, setAppendedNotes] = useState<NoteItem[]>([]);
  const notes = [...(initialNotes ?? []), ...appendedNotes];
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  const draft = useCaseTabStore((state) => state.tabState[caseId]?.notesDraft ?? "");
  const updateTabState = useCaseTabStore((state) => state.updateTabState);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSubmittedDraft = useRef("");

  async function autosave(body: string) {
    setSaveState("saving");
    setSaveError(null);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/notes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body }),
      });
      const responseBody = await res.json();
      if (!res.ok) {
        throw new Error(
          typeof responseBody.detail === "string" ? responseBody.detail : "Failed to save note",
        );
      }
      setAppendedNotes((prev) => [...prev, responseBody as NoteItem]);
      updateTabState(caseId, { notesDraft: "" });
      // Only mark this exact text as "submitted" on real success — setting
      // it before the request resolves would mean a failed autosave gets
      // silently treated as "already tried" and never retried on the next
      // debounce pause unless the user edits the text further (a real bug
      // caught in this phase's own self-review, same class as the
      // stale-cache findings Phase 14/15's code review caught elsewhere).
      lastSubmittedDraft.current = "";
      setSaveState("saved");
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save note");
      setSaveState("error");
    }
  }

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = draft.trim();
    if (!trimmed || trimmed === lastSubmittedDraft.current) {
      return;
    }
    debounceRef.current = setTimeout(() => {
      void autosave(trimmed);
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draft]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Investigator Notes</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {loading && <p className="text-muted-foreground text-sm">Loading notes…</p>}
        {!loading && error && (
          <p className="text-destructive text-sm" role="alert">
            {error}
          </p>
        )}
        {!loading && !error && (
          <div className="flex max-h-64 flex-col gap-2 overflow-y-auto">
            {notes.length === 0 && (
              <p className="text-muted-foreground text-sm">No notes yet on this case.</p>
            )}
            {notes.map((n) => (
              <div key={n.note_id} className="rounded-lg border p-2 text-sm">
                <p className="whitespace-pre-wrap">{n.body}</p>
                <p className="text-muted-foreground mt-1 text-xs">
                  {n.author_id ?? "System"} · {formatDateTime(n.created_at)}
                </p>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <label htmlFor={`notes-compose-${caseId}`} className="text-sm font-medium">
            Add a note
          </label>
          <textarea
            id={`notes-compose-${caseId}`}
            value={draft}
            onChange={(e) => {
              updateTabState(caseId, { notesDraft: e.target.value });
              if (saveState !== "idle") setSaveState("idle");
            }}
            placeholder="Write a note — it autosaves a couple seconds after you stop typing."
            className="border-input min-h-20 rounded-lg border bg-transparent p-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          />
          <p className="text-muted-foreground text-xs" aria-live="polite">
            {saveState === "saving" && "Saving…"}
            {saveState === "saved" && "Saved."}
            {saveState === "error" && saveError}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
