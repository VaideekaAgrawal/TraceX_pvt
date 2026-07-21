"use client";

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
import {
  DEFAULT_ALERT_FILTERS,
  type AlertFilters,
} from "@/components/dashboard/alert-query";
import {
  DETECTION_TYPE_LABELS,
  SEVERITY_ORDER,
  detectionTypeLabel,
  severityLabel,
} from "@/components/dashboard/format";
import type { InvestigatorWorkloadItem } from "@/lib/api/types";

// `Alert.status` (`db/models/detection.py`) is a free-text column
// ("open/assigned/closed" per its inline comment) with only "open" ever
// actually written by the pipeline today — offered as a fixed set here
// rather than a free-text input since those are the only values the
// backend's own writer comment documents as meaningful.
const STATUS_OPTIONS = ["open", "assigned", "closed"];
const PRIORITY_OPTIONS = ["P1", "P2", "P3", "P4"];
const DETECTION_TYPE_OPTIONS = Object.keys(DETECTION_TYPE_LABELS);

// Sentinel for "no filter" in the base-ui `Select` (it needs a real
// string value for the "All" item, not `undefined`/`null`).
const ALL = "__all__";

export function AlertFiltersBar({
  filters,
  onChange,
  investigators,
  isAdmin,
}: {
  filters: AlertFilters;
  onChange: (next: AlertFilters) => void;
  investigators: InvestigatorWorkloadItem[];
  isAdmin: boolean;
}) {
  function set<K extends keyof AlertFilters>(key: K, value: AlertFilters[K]) {
    onChange({ ...filters, [key]: value });
  }

  // "Unassigned only" and "Assigned to <investigator>" are mutually
  // exclusive filters — an alert can't simultaneously be unassigned and
  // assigned to someone. The backend rejects the combination with a 400
  // (real validation, this is a UX courtesy on top of that), but leaving
  // both controls independently settable let an admin silently get
  // `total_count=0` with no explanation. Enforce exclusivity directly in
  // the setters so the two controls can never disagree, rather than
  // relying on each `<Select>`/`<Checkbox>`'s `disabled` prop alone.
  function setAssignedTo(value: string) {
    onChange({ ...filters, assignedTo: value, unassignedOnly: value ? false : filters.unassignedOnly });
  }

  function setUnassignedOnly(checked: boolean) {
    onChange({ ...filters, unassignedOnly: checked, assignedTo: checked ? "" : filters.assignedTo });
  }

  const hasActiveFilters =
    JSON.stringify(filters) !== JSON.stringify(DEFAULT_ALERT_FILTERS);

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border p-3">
      <Field label="Status">
        <Select
          value={filters.status || ALL}
          onValueChange={(value) => set("status", value === ALL ? "" : String(value))}
        >
          <SelectTrigger size="sm" className="w-32" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All statuses</SelectItem>
            {STATUS_OPTIONS.map((status) => (
              <SelectItem key={status} value={status}>
                {status}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Priority">
        <Select
          value={filters.priority || ALL}
          onValueChange={(value) => set("priority", value === ALL ? "" : String(value))}
        >
          <SelectTrigger size="sm" className="w-28" aria-label="Priority">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All priorities</SelectItem>
            {PRIORITY_OPTIONS.map((priority) => (
              <SelectItem key={priority} value={priority}>
                {priority}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Severity">
        <Select
          value={filters.severity || ALL}
          onValueChange={(value) => set("severity", value === ALL ? "" : String(value))}
        >
          <SelectTrigger size="sm" className="w-32" aria-label="Severity">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All severities</SelectItem>
            {SEVERITY_ORDER.map((severity) => (
              <SelectItem key={severity} value={severity}>
                {severityLabel(severity)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Type">
        <Select
          value={filters.detectionType || ALL}
          onValueChange={(value) => set("detectionType", value === ALL ? "" : String(value))}
        >
          <SelectTrigger size="sm" className="w-40" aria-label="Type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All types</SelectItem>
            {DETECTION_TYPE_OPTIONS.map((type) => (
              <SelectItem key={type} value={type}>
                {detectionTypeLabel(type)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>

      <Field label="Min risk">
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          max={100}
          aria-label="Min risk"
          className="w-20"
          value={filters.minRiskScore}
          onChange={(e) => set("minRiskScore", e.target.value)}
        />
      </Field>

      <Field label="Max risk">
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          max={100}
          aria-label="Max risk"
          className="w-20"
          value={filters.maxRiskScore}
          onChange={(e) => set("maxRiskScore", e.target.value)}
        />
      </Field>

      <Field label="From">
        <Input
          type="date"
          aria-label="From date"
          className="w-36"
          value={filters.start}
          onChange={(e) => set("start", e.target.value)}
        />
      </Field>

      <Field label="To">
        <Input
          type="date"
          aria-label="To date"
          className="w-36"
          value={filters.end}
          onChange={(e) => set("end", e.target.value)}
        />
      </Field>

      {isAdmin && (
        <Field label="Assigned to">
          <Select
            value={filters.assignedTo || ALL}
            onValueChange={(value) => setAssignedTo(value === ALL ? "" : String(value))}
            disabled={filters.unassignedOnly}
          >
            <SelectTrigger
              size="sm"
              className="w-40"
              aria-label="Assigned to"
              title={
                filters.unassignedOnly
                  ? "Unset “Unassigned only” to filter by investigator"
                  : undefined
              }
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Any investigator</SelectItem>
              {investigators.map((inv) => (
                <SelectItem key={inv.user_id} value={inv.user_id}>
                  {inv.full_name} ({inv.open_case_count})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      )}

      <div className="flex items-center gap-1.5 pb-1.5">
        <Checkbox
          id="unassigned-only"
          checked={filters.unassignedOnly}
          disabled={!!filters.assignedTo}
          onCheckedChange={(checked) => setUnassignedOnly(!!checked)}
        />
        <Label
          htmlFor="unassigned-only"
          className="text-sm font-normal"
          title={
            filters.assignedTo
              ? "Clear the “Assigned to” filter to use this"
              : undefined
          }
        >
          Unassigned only
        </Label>
      </div>

      {hasActiveFilters && (
        <Button
          variant="ghost"
          size="sm"
          className="mb-0.5"
          onClick={() => onChange(DEFAULT_ALERT_FILTERS)}
        >
          Clear filters
        </Button>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-muted-foreground text-xs font-normal">{label}</Label>
      {children}
    </div>
  );
}
