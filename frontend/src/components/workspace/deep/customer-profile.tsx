"use client";

import { Badge } from "@/components/ui/badge";
import { formatDateTime, formatRiskScore } from "@/components/dashboard/format";
import { FlagBadge } from "@/components/workspace/triage/customer-snapshot";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageField as Field, TriageSection } from "@/components/workspace/triage/triage-section";
import type { CustomerProfileResponse } from "@/lib/api/types";

// `omitted_fields` -> plain-language label, per `investigation/
// customer_profile.py`'s own documented reasoning for each gap (no schema
// column exists for any of these). Shown as explicit "Not available" rows,
// not hidden — the honesty pattern this section's ROADMAP Phase 17 scope
// requires.
const OMITTED_FIELD_LABELS: Record<string, string> = {
  beneficial_owner: "Beneficial owner",
  linked_cards: "Linked cards",
  linked_loans: "Linked loans",
  linked_deposits: "Linked deposits",
  risk_score_trend: "Risk score trend",
};

function omittedFieldLabel(field: string): string {
  return OMITTED_FIELD_LABELS[field] ?? field;
}

function formatMoney(value: number | null): string {
  return value != null ? `₹${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : "—";
}

/**
 * L2 §5 — Complete Customer Profile, `GET .../profile` (ROADMAP Phase 17).
 * Superset of L1's Customer Snapshot (`triage/customer-snapshot.tsx`) plus
 * the L2-only fields (`investigation/customer_profile.py`): account/KYC
 * detail, expected-vs-actual volume variance, prior-SAR/alert counts.
 * `omitted_fields` rendered explicitly as "Not available" — never
 * hidden/blank — per this section's documented honesty requirement.
 */
export function CustomerProfileSection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const { data, loading, error } = useTriageFetch<CustomerProfileResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/profile`,
  );

  return (
    <TriageSection
      title="Complete Customer Profile"
      description="Full KYC, account, and behavioral-expectation detail for the primary account, including documented data gaps."
      loading={loading}
      error={error}
    >
      {data && (
        <div className="flex flex-col gap-4">
          <div>
            <p className="mb-1 text-xs font-medium text-muted-foreground">Identity &amp; KYC</p>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
              <Field label="Name" value={data.name ?? "—"} />
              <Field label="Entity Type" value={data.entity_type ?? "—"} />
              <Field label="Customer ID" value={data.customer_id ?? "—"} />
              <Field label="Occupation" value={data.occupation ?? "—"} />
              <Field label="Employer" value={data.employer ?? "—"} />
              <Field label="KYC Status" value={data.kyc_status ?? "—"} />
              <Field label="KYC Tier" value={data.kyc_tier ?? "—"} />
              <Field label="EDD Status" value={data.edd_status ?? "—"} />
              <Field label="Risk Rating" value={data.risk_rating ?? "—"} />
              <Field
                label="Declared Annual Income"
                value={
                  data.declared_annual_income != null
                    ? `${formatMoney(data.declared_annual_income)} (${data.income_bracket ?? "—"})`
                    : "—"
                }
              />
            </dl>
            <div className="mt-2 flex flex-wrap gap-2">
              <FlagBadge label="PEP" active={data.pep_status} />
              <FlagBadge label="Sanctions match" active={data.sanction_status} />
            </div>
          </div>

          <div className="border-t pt-3">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Account</p>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
              <Field label="Account Type" value={data.account_type ?? "—"} />
              <Field label="Bank" value={data.bank_name ?? "—"} />
              <Field label="Branch City" value={data.branch_city ?? "—"} />
              <Field label="Account Status" value={data.account_status ?? "—"} />
              <Field
                label="Opening Date"
                value={data.opening_date ? formatDateTime(data.opening_date) : "—"}
              />
              <Field label="Current Risk Score" value={formatRiskScore(data.current_risk_score)} />
            </dl>
          </div>

          <div className="border-t pt-3">
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              Expected vs. Actual Volume
            </p>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
              <Field label="Expected Monthly Volume" value={formatMoney(data.expected_monthly_volume)} />
              <Field
                label="Actual Monthly Volume (avg)"
                value={formatMoney(data.actual_monthly_volume_avg)}
              />
              <Field
                label="Variance Ratio"
                value={
                  data.expected_vs_actual_variance_ratio != null
                    ? `${data.expected_vs_actual_variance_ratio.toFixed(2)}×`
                    : "—"
                }
              />
            </dl>
          </div>

          <div className="border-t pt-3">
            <p className="mb-1 text-xs font-medium text-muted-foreground">Prior History</p>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
              <Field label="Prior SAR Count" value={String(data.prior_sar_count)} />
              <Field label="Total Prior Alerts" value={String(data.total_prior_alerts)} />
            </dl>
          </div>

          {data.sibling_accounts.length > 0 && (
            <div className="border-t pt-3">
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                Sibling Accounts ({data.sibling_accounts.length})
              </p>
              <div className="flex flex-col gap-1">
                {data.sibling_accounts.map((s) => (
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

          {data.omitted_fields.length > 0 && (
            <div className="border-t pt-3">
              <p className="mb-1 text-xs font-medium text-muted-foreground">
                Not Tracked in This System
              </p>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4">
                {data.omitted_fields.map((field) => (
                  <Field key={field} label={omittedFieldLabel(field)} value="Not available" />
                ))}
              </dl>
            </div>
          )}
        </div>
      )}
    </TriageSection>
  );
}
