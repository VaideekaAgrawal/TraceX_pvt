"use client";

import { useState, type FormEvent } from "react";
import { Pin } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDateTime } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { FilterField, TriageSection } from "@/components/workspace/triage/triage-section";
import { EVIDENCE_TYPES, type EvidenceCreateRequest, type EvidenceItem, type EvidenceType } from "@/lib/api/types";

const TYPE_LABELS: Record<EvidenceType, string> = {
  TRANSACTION: "Transaction",
  ACCOUNT: "Account",
  GRAPH_SNAPSHOT: "Graph snapshot",
  DOCUMENT: "Document reference",
  PATTERN: "Pattern",
  NOTE_REF: "Note reference",
};

// Which manual-form fields make sense for a given type — `ref_id` for
// anything that points at an existing entity, `file_path` only for
// `DOCUMENT` (a plain reference string, never an upload — see this file's
// own form copy below), neither for `GRAPH_SNAPSHOT` (no in-UI snapshot
// capture exists this phase, so it's created with `label` only rather than
// faking a payload — an honest gap, not a hidden one).
const REF_ID_TYPES: EvidenceType[] = ["TRANSACTION", "ACCOUNT", "PATTERN", "NOTE_REF"];

function refIdLabel(type: EvidenceType): string {
  switch (type) {
    case "TRANSACTION":
      return "Transaction ID";
    case "ACCOUNT":
      return "Account ID";
    case "PATTERN":
      return "Pattern / alert ID";
    case "NOTE_REF":
      return "Note ID";
    default:
      return "Reference ID";
  }
}

/**
 * L2 §7 — Evidence Management (ROADMAP Phase 18): bookmark a transaction or
 * account, pin evidence, list with a pinned-only filter. `POST .../evidence`
 * to create, `PATCH .../evidence/{id}/pin` to pin (one-directional — no
 * "unpin" route exists, so none is offered here either), `GET .../evidence`
 * to list.
 *
 * Bookmark UX (judgment call): rather than only a manual form, the two
 * quick-bookmark buttons read `selectedTxnId`/`selectedAccountId` —
 * state `deep-view.tsx` already lifts from the Investigation Graph/
 * Timeline's click-to-select interaction — so bookmarking whatever's
 * currently selected elsewhere on the page is one click, not a
 * copy-paste-the-id round trip through the manual form below it.
 *
 * Notes are deliberately NOT duplicated here — `triage/notes-panel.tsx`'s
 * single instance (mounted once, inside `TriageView`) already covers
 * "notes continuity," and Triage/Deep are both always mounted (CSS
 * visibility toggle, not conditional mount), so switching to Triage shows
 * the same live draft/list without a second autosave loop double-posting
 * the same note.
 */
export function EvidencePanel({
  caseId,
  selectedTxnId,
  selectedAccountId,
}: {
  caseId: string;
  selectedTxnId: string | null;
  selectedAccountId: string | null;
}) {
  const [pinnedOnly, setPinnedOnly] = useState(false);
  const url = `/api/cases/${encodeURIComponent(caseId)}/evidence${pinnedOnly ? "?pinned=true" : ""}`;
  const { data, loading, error, refetch } = useTriageFetch<EvidenceItem[]>(url);

  const [type, setType] = useState<EvidenceType>("TRANSACTION");
  const [refId, setRefId] = useState("");
  const [label, setLabel] = useState("");
  const [filePath, setFilePath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [pinningId, setPinningId] = useState<string | null>(null);

  async function submitEvidence(body: EvidenceCreateRequest) {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await fetch(`/api/cases/${encodeURIComponent(caseId)}/evidence`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const responseBody = await res.json();
      if (!res.ok) {
        throw new Error(
          typeof responseBody.detail === "string" ? responseBody.detail : "Failed to save evidence",
        );
      }
      setRefId("");
      setLabel("");
      setFilePath("");
      refetch();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to save evidence");
    } finally {
      setSubmitting(false);
    }
  }

  async function pin(evidenceId: string) {
    setPinningId(evidenceId);
    try {
      const res = await fetch(
        `/api/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidenceId)}/pin`,
        { method: "PATCH" },
      );
      if (!res.ok) throw new Error("Failed to pin evidence");
      refetch();
    } catch {
      // Surfaced via the list simply not updating — a dedicated per-row
      // error banner is more chrome than this action warrants; the pin
      // button stays enabled so the investigator can just retry it.
    } finally {
      setPinningId(null);
    }
  }

  function handleManualSubmit(e: FormEvent) {
    e.preventDefault();
    void submitEvidence({
      type,
      ref_id: REF_ID_TYPES.includes(type) && refId ? refId : undefined,
      label: label || undefined,
      file_path: type === "DOCUMENT" && filePath ? filePath : undefined,
    });
  }

  return (
    <TriageSection
      title="Evidence"
      description="Bookmark transactions, accounts, or other case artifacts; pin the ones that matter for the final decision."
      loading={loading}
      error={error}
      isEmpty={!!data && data.length === 0}
      emptyText={pinnedOnly ? "No pinned evidence yet." : "No evidence bookmarked on this case yet."}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!selectedTxnId || submitting}
            onClick={() =>
              void submitEvidence({ type: "TRANSACTION", ref_id: selectedTxnId ?? undefined })
            }
          >
            Bookmark selected transaction{selectedTxnId ? ` (${selectedTxnId})` : ""}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={!selectedAccountId || submitting}
            onClick={() =>
              void submitEvidence({ type: "ACCOUNT", ref_id: selectedAccountId ?? undefined })
            }
          >
            Bookmark selected account{selectedAccountId ? ` (${selectedAccountId})` : ""}
          </Button>
        </div>

        <form onSubmit={handleManualSubmit} className="flex flex-wrap items-end gap-3 rounded-lg border p-3">
          <FilterField label="Type">
            <Select value={type} onValueChange={(value) => setType(value as EvidenceType)}>
              <SelectTrigger size="sm" className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EVIDENCE_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {TYPE_LABELS[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterField>

          {REF_ID_TYPES.includes(type) && (
            <FilterField label={refIdLabel(type)}>
              <Input className="w-40" value={refId} onChange={(e) => setRefId(e.target.value)} />
            </FilterField>
          )}

          <FilterField label="Label (optional)">
            <Input className="w-48" value={label} onChange={(e) => setLabel(e.target.value)} />
          </FilterField>

          {type === "DOCUMENT" && (
            <FilterField label="Document reference (path/URL text)">
              <Input
                className="w-56"
                placeholder="e.g. shared-drive/case-123/kyc.pdf"
                value={filePath}
                onChange={(e) => setFilePath(e.target.value)}
              />
            </FilterField>
          )}

          <Button type="submit" size="sm" disabled={submitting}>
            Add evidence
          </Button>
        </form>
        {type === "DOCUMENT" && (
          <p className="text-muted-foreground -mt-2 text-xs">
            This is a text reference only, not a file upload — no upload storage exists in this
            system.
          </p>
        )}
        {submitError && (
          <p className="text-destructive text-sm" role="alert">
            {submitError}
          </p>
        )}

        <div className="flex items-center gap-1.5">
          <Checkbox
            id={`evidence-pinned-only-${caseId}`}
            checked={pinnedOnly}
            onCheckedChange={(checked) => setPinnedOnly(!!checked)}
          />
          <Label htmlFor={`evidence-pinned-only-${caseId}`} className="text-sm font-normal">
            Pinned only
          </Label>
        </div>

        <div className="flex flex-col gap-2">
          {(data ?? []).map((item) => (
            <div key={item.evidence_id} className="flex flex-wrap items-center gap-2 rounded-lg border p-2 text-sm">
              <Badge variant="outline">{TYPE_LABELS[item.type as EvidenceType] ?? item.type}</Badge>
              <span className="font-medium">{item.label || item.ref_id || item.evidence_id}</span>
              {item.ref_id && item.label && (
                <span className="text-muted-foreground">({item.ref_id})</span>
              )}
              {item.file_path && <span className="text-muted-foreground">{item.file_path}</span>}
              <span className="text-muted-foreground ml-auto text-xs">
                {item.added_by} · {formatDateTime(item.added_at)}
              </span>
              {item.pinned ? (
                <Badge variant="outline" className="border-primary/40 bg-primary/5 text-primary">
                  <Pin className="size-3" /> Pinned
                </Badge>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={pinningId === item.evidence_id}
                  onClick={() => void pin(item.evidence_id)}
                >
                  <Pin className="size-3" /> Pin
                </Button>
              )}
            </div>
          ))}
        </div>
      </div>
    </TriageSection>
  );
}
