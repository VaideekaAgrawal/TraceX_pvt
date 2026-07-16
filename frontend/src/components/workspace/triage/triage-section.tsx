import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Shared Card + loading/error/empty chrome for every L1 Triage section
 * (`use-triage-fetch.ts` is the data half of this pair). Each section fails
 * independently — an error here never blocks a sibling section from
 * rendering, since every section owns its own fetch.
 */
export function TriageSection({
  title,
  description,
  action,
  loading,
  error,
  isEmpty,
  emptyText = "No data available for this account.",
  children,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  loading: boolean;
  error: string | null;
  isEmpty?: boolean;
  emptyText?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{title}</CardTitle>
          {description && <p className="text-muted-foreground text-xs">{description}</p>}
        </div>
        {action && <CardAction>{action}</CardAction>}
      </CardHeader>
      <CardContent>
        {loading && <p className="text-muted-foreground text-sm">Loading…</p>}
        {!loading && error && (
          <p className="text-destructive text-sm" role="alert">
            {error}
          </p>
        )}
        {!loading && !error && isEmpty && (
          <p className="text-muted-foreground text-sm">{emptyText}</p>
        )}
        {!loading && !error && !isEmpty && children}
      </CardContent>
    </Card>
  );
}

/** Shared label/value pair for the `dl`-based field grids across L1 Triage sections. */
export function TriageField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
