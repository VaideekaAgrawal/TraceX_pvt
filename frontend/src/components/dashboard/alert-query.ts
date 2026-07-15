/**
 * Filter state + query-param serialization shared by `alert-table.tsx` and
 * `alert-filters.tsx`. Kept separate from both so the "what filters exist"
 * contract is one file, not duplicated across the component that owns the
 * state and the component that renders its controls.
 */

export interface AlertFilters {
  status: string;
  priority: string;
  severity: string;
  detectionType: string;
  minRiskScore: string;
  maxRiskScore: string;
  start: string;
  end: string;
  assignedTo: string;
  unassignedOnly: boolean;
}

export const DEFAULT_ALERT_FILTERS: AlertFilters = {
  status: "",
  priority: "",
  severity: "",
  detectionType: "",
  minRiskScore: "",
  maxRiskScore: "",
  start: "",
  end: "",
  assignedTo: "",
  unassignedOnly: false,
};

export type AlertSortKey = "risk_score" | "created_at" | "priority";
export type AlertSortDir = "asc" | "desc";

export interface AlertSortState {
  key: AlertSortKey;
  dir: AlertSortDir;
}

/**
 * The "To" filter is a `type="date"` input, so `filters.end` is a bare
 * `YYYY-MM-DD` string with no time component. `api.routes.alerts.
 * _AlertListParams.end` is parsed backend-side as an exact `datetime` and
 * compared with `<=` (correct, exact-instant semantics for that param) —
 * so passing the bare date through as-is lands on that date's midnight and
 * silently excludes almost the entire selected end date, the opposite of
 * what an inclusive "To: <date>" filter should do. Convert to the last
 * instant of that day here, at the one place the query string is built,
 * so the filter is genuinely inclusive of the selected end date.
 */
function endOfDayParam(dateOnly: string): string {
  return `${dateOnly}T23:59:59.999`;
}

/**
 * Builds the `GET /alerts` query string (via the `/api/alerts` BFF route)
 * for the given filters/sort/pagination. Field names on the left match
 * `AlertFilters`' camelCase UI state; on the right, `api.routes.
 * alerts._AlertListParams`' actual query param names — do not rename
 * either side independently.
 */
export function alertQueryParams(
  filters: AlertFilters,
  sort: AlertSortState | null,
  limit: number,
  offset: number,
): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.status) params.status = filters.status;
  if (filters.priority) params.priority = filters.priority;
  if (filters.severity) params.severity = filters.severity;
  if (filters.detectionType) params.detection_type = filters.detectionType;
  if (filters.minRiskScore) params.min_risk_score = filters.minRiskScore;
  if (filters.maxRiskScore) params.max_risk_score = filters.maxRiskScore;
  if (filters.start) params.start = filters.start;
  if (filters.end) params.end = endOfDayParam(filters.end);
  if (filters.assignedTo) params.assigned_to = filters.assignedTo;
  if (filters.unassignedOnly) params.unassigned_only = "true";
  if (sort) params.sort = `${sort.key}_${sort.dir}`;
  params.limit = String(limit);
  params.offset = String(offset);
  return params;
}
