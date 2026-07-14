"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AlertFiltersBar } from "@/components/dashboard/alert-filters";
import { AssignDialog } from "@/components/dashboard/assign-dialog";
import { BulkAssignBar } from "@/components/dashboard/bulk-assign-bar";
import { PaginationControls } from "@/components/dashboard/pagination-controls";
import {
  DEFAULT_ALERT_FILTERS,
  alertQueryParams,
  type AlertFilters,
  type AlertSortDir,
  type AlertSortKey,
  type AlertSortState,
} from "@/components/dashboard/alert-query";
import {
  detectionTypeLabel,
  formatDateTime,
  formatRiskScore,
  severityBadgeClassName,
  severityLabel,
} from "@/components/dashboard/format";
import { useRole } from "@/lib/auth/auth-provider";
import type {
  AlertListItem,
  AlertListResponse,
  InvestigatorWorkloadItem,
} from "@/lib/api/types";

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 25;

/**
 * Owns filter/sort/pagination state and fetches `/api/alerts` on change
 * (plain `useState`, no Zustand — reserved starting Phase 15 per the task
 * brief). `initialData` seeds the first render so there's no fetch-on-
 * mount flicker, as long as the caller's server-side `listAlerts(...)`
 * call used the same defaults (`limit=25, offset=0`, no filters/sort) —
 * see `dashboard/page.tsx`.
 */
export function AlertTable({
  initialData,
  onAssignSuccess,
}: {
  initialData: AlertListResponse;
  onAssignSuccess?: () => void;
}) {
  const role = useRole();
  const isAdmin = role === "ADMIN_COMPLIANCE";

  const [filters, setFilters] = useState<AlertFilters>(DEFAULT_ALERT_FILTERS);
  const [sort, setSort] = useState<AlertSortState | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [data, setData] = useState<AlertListResponse>(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [workload, setWorkload] = useState<InvestigatorWorkloadItem[]>([]);

  const skipNextFetch = useRef(true);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = alertQueryParams(filters, sort, pageSize, page * pageSize);
      const qs = new URLSearchParams(params).toString();
      const res = await fetch(`/api/alerts?${qs}`, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(typeof body.detail === "string" ? body.detail : "Failed to load alerts");
      }
      setData(body as AlertListResponse);
      setSelected(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load alerts");
    } finally {
      setLoading(false);
    }
  }, [filters, sort, page, pageSize]);

  useEffect(() => {
    if (skipNextFetch.current) {
      skipNextFetch.current = false;
      return;
    }
    void fetchAlerts();
  }, [fetchAlerts]);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    fetch("/api/alerts/workload", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((body: { investigators: InvestigatorWorkloadItem[] } | null) => {
        if (!cancelled && body) setWorkload(body.investigators);
      })
      .catch(() => {
        // Non-fatal: the filter bar's "assigned to" filter and the assign
        // dialogs just render with an empty investigator list.
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  function updateFilters(next: AlertFilters) {
    setFilters(next);
    setPage(0);
  }

  function toggleSort(key: AlertSortKey) {
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "desc" as AlertSortDir };
      if (prev.dir === "desc") return { key, dir: "asc" as AlertSortDir };
      return null; // third click on the same column -> back to Recommended order
    });
    setPage(0);
  }

  function toggleRow(alertId: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(alertId);
      else next.delete(alertId);
      return next;
    });
  }

  function handleAssigned() {
    void fetchAlerts();
    onAssignSuccess?.();
  }

  const allSelected = data.items.length > 0 && selected.size === data.items.length;
  const columnCount = isAdmin ? 10 : 8;

  return (
    <div className="flex flex-col gap-3">
      <AlertFiltersBar
        filters={filters}
        onChange={updateFilters}
        investigators={workload}
        isAdmin={isAdmin}
      />

      {isAdmin && selected.size > 0 && (
        <BulkAssignBar
          selectedAlertIds={[...selected]}
          investigators={workload}
          onDone={handleAssigned}
          onClearSelection={() => setSelected(new Set())}
        />
      )}

      {error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}

      <div className="overflow-hidden rounded-xl ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              {isAdmin && (
                <TableHead className="w-8">
                  <Checkbox
                    checked={allSelected}
                    onCheckedChange={(checked) =>
                      setSelected(checked ? new Set(data.items.map((a) => a.alert_id)) : new Set())
                    }
                    aria-label="Select all alerts on this page"
                  />
                </TableHead>
              )}
              <TableHead>Account</TableHead>
              <TableHead>Type</TableHead>
              <SortableHead label="Risk Score" sortKey="risk_score" sort={sort} onSort={toggleSort} />
              <SortableHead label="Priority" sortKey="priority" sort={sort} onSort={toggleSort} />
              <TableHead>Severity</TableHead>
              <SortableHead label="Created" sortKey="created_at" sort={sort} onSort={toggleSort} />
              <TableHead>Case</TableHead>
              <TableHead>Assigned To</TableHead>
              {isAdmin && <TableHead className="w-28">Action</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={columnCount} className="text-muted-foreground py-8 text-center">
                  No alerts match the current filters.
                </TableCell>
              </TableRow>
            )}
            {data.items.map((alert) => (
              <AlertRow
                key={alert.alert_id}
                alert={alert}
                isAdmin={isAdmin}
                selected={selected.has(alert.alert_id)}
                onToggleSelected={(checked) => toggleRow(alert.alert_id, checked)}
                investigators={workload}
                onAssigned={handleAssigned}
              />
            ))}
          </TableBody>
        </Table>
      </div>

      <PaginationControls
        page={page}
        pageSize={pageSize}
        totalCount={data.total_count}
        pageSizeOptions={PAGE_SIZE_OPTIONS}
        loading={loading}
        onPageChange={setPage}
        onPageSizeChange={(size) => {
          setPageSize(size);
          setPage(0);
        }}
      />
    </div>
  );
}

function SortableHead({
  label,
  sortKey,
  sort,
  onSort,
}: {
  label: string;
  sortKey: AlertSortKey;
  sort: AlertSortState | null;
  onSort: (key: AlertSortKey) => void;
}) {
  const active = sort?.key === sortKey;
  const Icon = active ? (sort?.dir === "desc" ? ArrowDown : ArrowUp) : ArrowUpDown;
  return (
    <TableHead>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="hover:text-foreground flex items-center gap-1"
      >
        {label}
        <Icon className="text-muted-foreground size-3.5" />
      </button>
    </TableHead>
  );
}

function AlertRow({
  alert,
  isAdmin,
  selected,
  onToggleSelected,
  investigators,
  onAssigned,
}: {
  alert: AlertListItem;
  isAdmin: boolean;
  selected: boolean;
  onToggleSelected: (checked: boolean) => void;
  investigators: InvestigatorWorkloadItem[];
  onAssigned: () => void;
}) {
  return (
    <TableRow data-state={selected ? "selected" : undefined}>
      {isAdmin && (
        <TableCell>
          <Checkbox
            checked={selected}
            onCheckedChange={(checked) => onToggleSelected(checked)}
            aria-label={`Select alert ${alert.alert_id}`}
          />
        </TableCell>
      )}
      <TableCell className="font-medium">
        {alert.case_id ? (
          // The Investigation Workspace itself doesn't exist until Phase
          // 15 — this is a sensible deep-link target, not a working
          // destination page yet.
          <Link
            href={`/workspace?case=${encodeURIComponent(alert.case_id)}`}
            className="hover:underline"
          >
            {alert.primary_account_id}
          </Link>
        ) : (
          alert.primary_account_id
        )}
      </TableCell>
      <TableCell>{detectionTypeLabel(alert.detection_type)}</TableCell>
      <TableCell>{formatRiskScore(alert.risk_score)}</TableCell>
      <TableCell>
        <Badge variant="outline">{alert.priority}</Badge>
      </TableCell>
      <TableCell>
        <Badge variant="outline" className={severityBadgeClassName(alert.severity)}>
          {severityLabel(alert.severity)}
        </Badge>
      </TableCell>
      <TableCell className="text-muted-foreground">{formatDateTime(alert.created_at)}</TableCell>
      <TableCell className="text-muted-foreground">
        {alert.case_status ?? "No case yet"}
      </TableCell>
      <TableCell>{alert.assigned_to_name ?? "Unassigned"}</TableCell>
      {isAdmin && (
        <TableCell>
          <AssignDialog
            alertId={alert.alert_id}
            currentAssignedToName={alert.assigned_to_name}
            investigators={investigators}
            onAssigned={onAssigned}
          />
        </TableCell>
      )}
    </TableRow>
  );
}
