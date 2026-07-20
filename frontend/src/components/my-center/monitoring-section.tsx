"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { detectionTypeLabel, formatDateTime, formatRiskScore } from "@/components/dashboard/format";
import { useRole } from "@/lib/auth/auth-provider";
import { FilterField } from "@/components/workspace/triage/triage-section";
import {
  WATCH_ENTITY_TYPES,
  type AddWatchlistRequest,
  type WatchEntityTypeValue,
  type WatchlistEntryModel,
} from "@/lib/api/types";

const ENTITY_TYPE_LABELS: Record<WatchEntityTypeValue, string> = {
  CUSTOMER: "Customer",
  ACCOUNT: "Account",
  DEVICE: "Device",
  MERCHANT: "Merchant",
  COMPANY: "Company",
};

/**
 * My Center → Monitoring (ROADMAP Phase 21). `GET /watchlist` is open to
 * any authenticated user; add/remove are Admin/Compliance only server-side
 * (403 otherwise) — the add form and per-row Remove button below only ever
 * render for `isAdmin`, backstopped by the real 403 but not relied on as
 * the primary UX, same posture as `decision-panel.tsx`/`str-report-panel.
 * tsx`'s own role gating this same phase.
 *
 * "Monitoring (n)" is `entries.length` — `GET /watchlist` already only
 * returns active entries (`WatchlistRepository.list_active`, confirmed by
 * reading that repository method directly rather than assumed), so no
 * separate client-side `.filter(e => e.active)` is needed on top of it.
 *
 * Each entry's `alerts` list (every alert raised at/after the entry was
 * added, newest first — `investigation/watchlist.py::_alerts_since`) is
 * the clickable part: clicking a row with a `case_id` navigates to that
 * case via the Investigation Workspace's own `?case=` deep link
 * (`workspace-shell.tsx`), the only cross-page case-opening mechanism that
 * exists outside the workspace's own Zustand tab store — My Center sits
 * outside `WorkspaceShell`'s mount tree, so `useOpenCaseTab`/the tab store
 * aren't available here (confirmed by reading `workspace-shell.tsx`
 * before writing this). An alert with no `case_id` yet renders as
 * non-clickable plain text instead of a broken link.
 */
export function MonitoringSection({ initialEntries }: { initialEntries: WatchlistEntryModel[] }) {
  const role = useRole();
  const isAdmin = role === "ADMIN_COMPLIANCE";

  const [entries, setEntries] = useState(initialEntries);
  const [listError, setListError] = useState<string | null>(null);

  const [entityType, setEntityType] = useState<WatchEntityTypeValue>("ACCOUNT");
  const [entityValue, setEntityValue] = useState("");
  const [reason, setReason] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  const [removingId, setRemovingId] = useState<string | null>(null);

  async function refresh() {
    try {
      const res = await fetch("/api/watchlist", { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to load watchlist");
      }
      setEntries(body as WatchlistEntryModel[]);
      setListError(null);
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to load watchlist");
    }
  }

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    if (!entityValue.trim()) {
      setAddError("An entity value (customer or account ID) is required.");
      return;
    }
    setAdding(true);
    setAddError(null);
    try {
      const body: AddWatchlistRequest = {
        entity_type: entityType,
        entity_value: entityValue.trim(),
        reason: reason.trim() || undefined,
      };
      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const responseBody = await res.json();
      if (!res.ok) {
        throw new Error(
          typeof responseBody.detail === "string" ? responseBody.detail : "Failed to add watchlist entry",
        );
      }
      setEntityValue("");
      setReason("");
      await refresh();
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to add watchlist entry");
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(entryId: string) {
    setRemovingId(entryId);
    try {
      const res = await fetch(`/api/watchlist/${encodeURIComponent(entryId)}`, { method: "DELETE" });
      if (!res.ok) {
        const responseBody = await res.json().catch(() => ({}));
        throw new Error(
          typeof responseBody.detail === "string" ? responseBody.detail : "Failed to remove entry",
        );
      }
      await refresh();
    } catch (err) {
      setListError(err instanceof Error ? err.message : "Failed to remove entry");
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle>Monitoring</CardTitle>
          <Badge variant="outline">{entries.length}</Badge>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isAdmin && (
          <form
            onSubmit={(e) => void handleAdd(e)}
            className="flex flex-wrap items-end gap-3 rounded-lg border p-3"
          >
            <FilterField label="Entity type">
              <Select
                value={entityType}
                onValueChange={(value) => setEntityType(value as WatchEntityTypeValue)}
              >
                <SelectTrigger size="sm" className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WATCH_ENTITY_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {ENTITY_TYPE_LABELS[t]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FilterField>
            <FilterField label="Customer / account ID">
              <Input
                className="w-56"
                value={entityValue}
                onChange={(e) => setEntityValue(e.target.value)}
              />
            </FilterField>
            <FilterField label="Reason (optional)">
              <Input className="w-64" value={reason} onChange={(e) => setReason(e.target.value)} />
            </FilterField>
            <Button type="submit" size="sm" disabled={adding}>
              {adding ? "Adding…" : "Add to watchlist"}
            </Button>
          </form>
        )}
        {addError && (
          <Alert variant="destructive">
            <AlertTitle>Failed to add entry</AlertTitle>
            <AlertDescription>{addError}</AlertDescription>
          </Alert>
        )}
        {listError && (
          <Alert variant="destructive">
            <AlertTitle>Watchlist error</AlertTitle>
            <AlertDescription>{listError}</AlertDescription>
          </Alert>
        )}

        {entries.length === 0 ? (
          <p className="text-muted-foreground text-sm">No entities are currently under monitoring.</p>
        ) : (
          <div className="overflow-hidden rounded-lg ring-1 ring-foreground/10">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Account / Network Name</TableHead>
                  <TableHead>Monitoring Reason</TableHead>
                  <TableHead>Date Added</TableHead>
                  <TableHead>Current Risk</TableHead>
                  <TableHead>Latest Activity</TableHead>
                  <TableHead>Alerts Since Added</TableHead>
                  {isAdmin && <TableHead />}
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry) => (
                  <TableRow key={entry.entry_id}>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="font-medium">{entry.display_name ?? "—"}</span>
                        <span className="text-muted-foreground text-xs">
                          <Badge variant="outline" className="mr-1">
                            {ENTITY_TYPE_LABELS[entry.entity_type as WatchEntityTypeValue] ??
                              entry.entity_type}
                          </Badge>
                          {entry.entity_value}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{entry.reason || "—"}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(entry.created_at)}
                    </TableCell>
                    <TableCell>{formatRiskScore(entry.current_risk)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {entry.latest_activity ? formatDateTime(entry.latest_activity) : "—"}
                    </TableCell>
                    <TableCell>
                      {entry.alerts.length === 0 ? (
                        <span className="text-muted-foreground text-xs">None yet</span>
                      ) : (
                        <div className="flex flex-col gap-1">
                          {entry.alerts.map((alert) =>
                            alert.case_id ? (
                              <Link
                                key={alert.alert_id}
                                href={`/workspace?case=${encodeURIComponent(alert.case_id)}`}
                                className="text-primary flex items-center gap-1 text-xs underline-offset-2 hover:underline"
                              >
                                {detectionTypeLabel(alert.detection_type)} ·{" "}
                                {formatRiskScore(alert.risk_score)} · {formatDateTime(alert.created_at)}
                              </Link>
                            ) : (
                              <span
                                key={alert.alert_id}
                                className="text-muted-foreground text-xs"
                                title="No case opened for this alert yet"
                              >
                                {detectionTypeLabel(alert.detection_type)} ·{" "}
                                {formatRiskScore(alert.risk_score)} · {formatDateTime(alert.created_at)}{" "}
                                (no case yet)
                              </span>
                            ),
                          )}
                        </div>
                      )}
                    </TableCell>
                    {isAdmin && (
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={removingId === entry.entry_id}
                          onClick={() => void handleRemove(entry.entry_id)}
                        >
                          {removingId === entry.entry_id ? "Removing…" : "Remove"}
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
