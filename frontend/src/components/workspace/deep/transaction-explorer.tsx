"use client";

import { useCallback, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDateTime } from "@/components/dashboard/format";
import { PaginationControls } from "@/components/dashboard/pagination-controls";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { FilterField, TriageSection } from "@/components/workspace/triage/triage-section";
import type { TransactionSearchItem, TransactionSearchResponse } from "@/lib/api/types";

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 10;
const ALL = "__all__";

interface ExplorerFilterState {
  minAmount: string;
  maxAmount: string;
  start: string;
  end: string;
  direction: "" | "in" | "out";
  txnType: string;
  sort: string;
}

const DEFAULT_FILTERS: ExplorerFilterState = {
  minAmount: "",
  maxAmount: "",
  start: "",
  end: "",
  direction: "",
  txnType: "",
  sort: "timestamp_desc",
};

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: "timestamp_desc", label: "Newest first" },
  { value: "timestamp_asc", label: "Oldest first" },
  { value: "amount_desc", label: "Amount: high to low" },
  { value: "amount_asc", label: "Amount: low to high" },
];

/**
 * `filters.end` is a bare `YYYY-MM-DD` string from a `type="date"` input;
 * the backend parses `end` as an exact `datetime` compared with `<=`, so
 * passing it through as-is lands on that date's midnight and silently
 * excludes almost the entire selected end day — same fix as
 * `alert-query.ts::endOfDayParam` / `transaction-summary.tsx`'s identical
 * local convention, applied here too.
 */
function endOfDayParam(dateOnly: string): string {
  return `${dateOnly}T23:59:59.999`;
}

function buildSearchUrl(
  caseId: string,
  accountId: string | null,
  filters: ExplorerFilterState,
  page: number,
  pageSize: number,
): string {
  const qs = new URLSearchParams();
  if (filters.minAmount) qs.set("min_amount", filters.minAmount);
  if (filters.maxAmount) qs.set("max_amount", filters.maxAmount);
  if (filters.start) qs.set("start", filters.start);
  if (filters.end) qs.set("end", endOfDayParam(filters.end));
  if (filters.direction) qs.set("direction", filters.direction);
  if (filters.txnType) qs.set("txn_type", filters.txnType);
  qs.set("sort", filters.sort);
  qs.set("limit", String(pageSize));
  qs.set("offset", String(page * pageSize));

  const base = accountId
    ? `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/transactions/search`
    : `/api/cases/${encodeURIComponent(caseId)}/transactions/search`;
  return `${base}?${qs.toString()}`;
}

function toCsv(items: TransactionSearchItem[]): string {
  const header = [
    "txn_id",
    "timestamp",
    "amount",
    "channel",
    "txn_type",
    "source_account",
    "dest_account",
    "source_branch_city",
    "dest_branch_city",
    "source_account_type",
    "dest_account_type",
    "direction",
    "is_laundering",
  ];
  const rows = items.map((item) =>
    header
      .map((key) => {
        const value = item[key as keyof TransactionSearchItem];
        const cell = value === null || value === undefined ? "" : String(value);
        // Minimal CSV escaping — quote any cell containing a comma, quote,
        // or newline, doubling embedded quotes.
        return /[",\n]/.test(cell) ? `"${cell.replace(/"/g, '""')}"` : cell;
      })
      .join(","),
  );
  return [header.join(","), ...rows].join("\n");
}

/**
 * L2 §4 — Transaction Explorer, wired to both `GET /transactions/search`
 * (case-wide) and `GET .../accounts/{account_id}/transactions/search`
 * (account-scoped, `backend/api/routes/l2.py`) — ROADMAP Phase 17. CSV
 * export is client-side only, over the currently-fetched page of results —
 * there is no server-side export endpoint (`investigation/
 * transaction_search.py`'s own docstring: "this JSON result set itself is
 * the exportable artifact"), so this deliberately does NOT claim to export
 * more than what's on screen.
 */
export function TransactionExplorerSection({
  caseId,
  accountId,
}: {
  caseId: string;
  accountId: string;
}) {
  const [scope, setScope] = useState<"account" | "case">("account");
  const [filters, setFilters] = useState<ExplorerFilterState>(DEFAULT_FILTERS);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);

  const scopedAccountId = scope === "account" ? accountId : null;

  const url = useMemo(
    () => buildSearchUrl(caseId, scopedAccountId, filters, page, pageSize),
    [caseId, scopedAccountId, filters, page, pageSize],
  );
  const { data, loading, error } = useTriageFetch<TransactionSearchResponse>(url);

  function updateFilter<K extends keyof ExplorerFilterState>(key: K, value: ExplorerFilterState[K]) {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(0);
  }

  const handleExportCsv = useCallback(() => {
    if (!data || data.items.length === 0) return;
    const csv = toCsv(data.items);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${caseId}-transactions-page-${page + 1}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [data, caseId, page]);

  const hasActiveFilters = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);

  return (
    <TriageSection
      title="Transaction Explorer"
      description="Searchable, filterable, sortable transaction table. CSV export covers only the currently loaded page — there is no server-side export."
      loading={loading}
      error={error}
      isEmpty={!!data && data.items.length === 0}
      emptyText="No transactions match the current filters."
      action={
        <Button variant="outline" size="sm" onClick={handleExportCsv} disabled={!data || data.items.length === 0}>
          Export page as CSV
        </Button>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-4 rounded-lg border p-3">
          <FilterField label="Scope">
            <Select value={scope} onValueChange={(value) => { setScope(value as "account" | "case"); setPage(0); }}>
              <SelectTrigger size="sm" className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="account">This account only</SelectItem>
                <SelectItem value="case">Whole case (all linked accounts)</SelectItem>
              </SelectContent>
            </Select>
          </FilterField>

          <FilterField label="Sort">
            <Select value={filters.sort} onValueChange={(value) => updateFilter("sort", String(value))}>
              <SelectTrigger size="sm" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SORT_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FilterField>

          <FilterField label="Direction">
            <Select
              value={filters.direction || ALL}
              onValueChange={(value) => updateFilter("direction", value === ALL ? "" : (String(value) as "in" | "out"))}
            >
              <SelectTrigger size="sm" className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>Any</SelectItem>
                <SelectItem value="in">Inbound</SelectItem>
                <SelectItem value="out">Outbound</SelectItem>
              </SelectContent>
            </Select>
          </FilterField>

          <FilterField label="Min amount">
            <Input
              type="number"
              inputMode="decimal"
              className="w-28"
              value={filters.minAmount}
              onChange={(e) => updateFilter("minAmount", e.target.value)}
            />
          </FilterField>
          <FilterField label="Max amount">
            <Input
              type="number"
              inputMode="decimal"
              className="w-28"
              value={filters.maxAmount}
              onChange={(e) => updateFilter("maxAmount", e.target.value)}
            />
          </FilterField>
          <FilterField label="From">
            <Input type="date" className="w-36" value={filters.start} onChange={(e) => updateFilter("start", e.target.value)} />
          </FilterField>
          <FilterField label="To">
            <Input type="date" className="w-36" value={filters.end} onChange={(e) => updateFilter("end", e.target.value)} />
          </FilterField>
          <FilterField label="Transaction type">
            <Input
              className="w-36"
              placeholder="e.g. transfer"
              value={filters.txnType}
              onChange={(e) => updateFilter("txnType", e.target.value)}
            />
          </FilterField>

          {hasActiveFilters && (
            <Button variant="ghost" size="sm" onClick={() => { setFilters(DEFAULT_FILTERS); setPage(0); }}>
              Reset filters
            </Button>
          )}
        </div>

        {scope === "case" && (
          <p className="text-muted-foreground text-xs">
            Whole-case search: &quot;direction&quot; is relative to the whole set of case-linked
            accounts, not this one account — each result row&apos;s own <code>direction</code> is
            null in this mode (only meaningful for a single reference account).
          </p>
        )}

        {data && data.items.length > 0 && (
          <>
            <div className="overflow-hidden rounded-lg ring-1 ring-foreground/10">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Amount</TableHead>
                    <TableHead>Channel</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Destination</TableHead>
                    <TableHead>Direction</TableHead>
                    <TableHead>Flag</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((item) => (
                    <TableRow key={item.txn_id}>
                      <TableCell className="text-muted-foreground">{formatDateTime(item.timestamp)}</TableCell>
                      <TableCell>₹{item.amount.toLocaleString()}</TableCell>
                      <TableCell className="text-muted-foreground">{item.channel}</TableCell>
                      <TableCell className="text-muted-foreground">{item.txn_type}</TableCell>
                      <TableCell>
                        {item.source_account}
                        {item.source_branch_city && (
                          <span className="text-muted-foreground"> ({item.source_branch_city})</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {item.dest_account}
                        {item.dest_branch_city && (
                          <span className="text-muted-foreground"> ({item.dest_branch_city})</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {item.direction ? (
                          <Badge variant="outline">{item.direction === "in" ? "Inbound" : "Outbound"}</Badge>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {item.is_laundering && (
                          <Badge
                            variant="outline"
                            className="border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400"
                          >
                            Flagged
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
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
          </>
        )}
      </div>
    </TriageSection>
  );
}
