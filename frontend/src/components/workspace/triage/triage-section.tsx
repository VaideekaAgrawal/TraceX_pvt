import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";

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

/**
 * Shared label + arbitrary-control wrapper for filter bars (an `<Input>`,
 * `<Select>`, or `<Slider>` under a small muted label) — distinct from
 * `TriageField` above, which pairs a label with a static *value*, not an
 * interactive control. Used by both L2 filter panels (`deep/
 * investigation-graph.tsx`, `deep/transaction-explorer.tsx`) — factored out
 * here rather than left as two identical local copies.
 */
export function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-muted-foreground text-xs font-normal">{label}</Label>
      {children}
    </div>
  );
}
