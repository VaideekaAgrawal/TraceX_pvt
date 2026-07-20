/**
 * Shared display formatting for the Dashboard feature — plain-language
 * labels and severity color classes, kept in one place so the summary
 * cards, both charts, and the alert table agree on what "CRITICAL" looks
 * like. Every color mapping here is paired with a text label at every call
 * site (never color alone), matching this codebase's "Signals (Why
 * Flagged)" convention for analyst-facing risk presentation.
 */

// `db/enums.py::RiskLevel`, low -> high.
export const SEVERITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const;

export const SEVERITY_LABELS: Record<string, string> = {
  LOW: "Low",
  MEDIUM: "Medium",
  HIGH: "High",
  CRITICAL: "Critical",
};

// Badge className overrides (paired with `variant="outline"`) — text label
// always accompanies the color, per the cross-phase invariant against
// color-only status signaling.
export const SEVERITY_BADGE_CLASS: Record<string, string> = {
  LOW: "border-border text-muted-foreground",
  MEDIUM: "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  HIGH: "border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400",
  CRITICAL: "border-red-600 bg-red-600/15 text-red-700 font-semibold dark:text-red-400",
};

// `db/enums.py::DetectionType` -> plain-language label. Extend alongside
// that enum, not independently.
export const DETECTION_TYPE_LABELS: Record<string, string> = {
  layering: "Layering",
  round_trip: "Round-tripping",
  structuring: "Structuring",
  dormancy: "Dormant reactivation",
  profile_mismatch: "Profile mismatch",
};

export function detectionTypeLabel(detectionType: string): string {
  return DETECTION_TYPE_LABELS[detectionType] ?? detectionType;
}

export function severityLabel(severity: string): string {
  return SEVERITY_LABELS[severity] ?? severity;
}

export function severityBadgeClassName(severity: string): string {
  return SEVERITY_BADGE_CLASS[severity] ?? "border-border text-muted-foreground";
}

export function formatRiskScore(score: number | null | undefined): string {
  return typeof score === "number" ? score.toFixed(1) : "—";
}

export function formatDateTime(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Compact "short date + time" — used for per-edge labels on cytoscape
// canvases (`deep/graph-replay.tsx`) where `formatDateTime`'s full
// year/month/day/time is too wide to render legibly next to an edge, but a
// bare `HH:mm` alone would be ambiguous across a dataset whose dormancy/
// reactivation patterns can span months between two revealed transactions.
export function formatShortDateTime(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDate(isoDate: string): string {
  const parsed = new Date(`${isoDate}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
