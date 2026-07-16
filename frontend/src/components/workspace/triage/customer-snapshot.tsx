"use client";

import { Badge } from "@/components/ui/badge";
import { formatRiskScore } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageField as Field, TriageSection } from "@/components/workspace/triage/triage-section";
import type { CustomerSnapshotResponse, GeoRiskResponse } from "@/lib/api/types";

/**
 * L1 Triage §3 — Customer Snapshot, with Geo Risk (§3b) as an inline row
 * inside the same card rather than its own section, per spec (separate
 * backend route, same UI card).
 */
export function CustomerSnapshotSection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const snapshotUrl = `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/customer-snapshot`;
  const geoUrl = `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/geo-risk`;

  const snapshot = useTriageFetch<CustomerSnapshotResponse>(snapshotUrl);
  const geo = useTriageFetch<GeoRiskResponse>(geoUrl);

  return (
    <TriageSection
      title="Customer Snapshot"
      description="Identity, KYC/EDD status, and geographic risk for the primary account."
      loading={snapshot.loading}
      error={snapshot.error}
    >
      {snapshot.data && (
        <div className="flex flex-col gap-4">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
            <Field label="Name" value={snapshot.data.name ?? "—"} />
            <Field label="Entity Type" value={snapshot.data.entity_type ?? "—"} />
            <Field label="Customer ID" value={snapshot.data.customer_id ?? "—"} />
            <Field label="Occupation" value={snapshot.data.occupation ?? "—"} />
            <Field label="KYC Status" value={snapshot.data.kyc_status ?? "—"} />
            <Field label="EDD Status" value={snapshot.data.edd_status ?? "—"} />
            <Field label="Risk Rating" value={snapshot.data.risk_rating ?? "—"} />
            <Field
              label="Declared Annual Income"
              value={
                snapshot.data.declared_annual_income != null
                  ? `₹${snapshot.data.declared_annual_income.toLocaleString()} (${snapshot.data.income_bracket ?? "—"})`
                  : "—"
              }
            />
          </dl>

          <div className="flex flex-wrap gap-2">
            <FlagBadge label="PEP" active={snapshot.data.pep_status} />
            <FlagBadge label="Sanctions match" active={snapshot.data.sanction_status} />
          </div>

          <div className="border-t pt-3">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Geographic Risk</p>
            {geo.loading && <p className="text-muted-foreground text-sm">Loading…</p>}
            {!geo.loading && geo.error && (
              <p className="text-destructive text-sm" role="alert">
                {geo.error}
              </p>
            )}
            {!geo.loading && !geo.error && geo.data && (
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
                <Field label="Branch City" value={geo.data.branch_city ?? "—"} />
                <Field label="Bank" value={geo.data.bank_name ?? "—"} />
                <Field
                  label="Counterparty Banks"
                  value={`${geo.data.counterparty_bank_count}${geo.data.counterparty_banks.length ? ` (${geo.data.counterparty_banks.join(", ")})` : ""}`}
                />
                <Field
                  label="Counterparty Cities"
                  value={`${geo.data.counterparty_city_count}${geo.data.counterparty_cities.length ? ` (${geo.data.counterparty_cities.join(", ")})` : ""}`}
                />
              </dl>
            )}
          </div>

          {snapshot.data.sibling_accounts.length > 0 && (
            <div className="border-t pt-3">
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                Sibling Accounts ({snapshot.data.sibling_accounts.length})
              </p>
              <div className="flex flex-col gap-1">
                {snapshot.data.sibling_accounts.map((s) => (
                  <div key={s.account_id} className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium">{s.account_id}</span>
                    <span className="text-muted-foreground">{s.account_type}</span>
                    <span className="text-muted-foreground">
                      {s.branch_city ?? "—"} · {s.bank_name ?? "—"}
                    </span>
                    <Badge variant="outline">{s.status}</Badge>
                    <span className="text-muted-foreground">
                      Risk: {formatRiskScore(s.current_risk_score)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </TriageSection>
  );
}

function FlagBadge({ label, active }: { label: string; active: boolean | null }) {
  if (active === null) {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        {label}: Unknown
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className={
        active
          ? "border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400"
          : "border-border text-muted-foreground"
      }
    >
      {label}: {active ? "Yes" : "No"}
    </Badge>
  );
}
