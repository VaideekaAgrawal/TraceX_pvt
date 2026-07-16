/**
 * Shapes mirrored from the real backend routes this phase wires up:
 * `POST /auth/login`, `GET /auth/me` (`backend/api/routes/auth.py`).
 *
 * Keep these in lockstep with the backend's Pydantic response models —
 * don't invent fields the backend doesn't actually return.
 */

// `db/enums.py::UserRole` — exactly two roles, string values match the
// backend's `UserRole.value` exactly (`"INVESTIGATOR"` / `"ADMIN_COMPLIANCE"`).
// Do not add a third role here without a corresponding backend change.
export const USER_ROLES = ["INVESTIGATOR", "ADMIN_COMPLIANCE"] as const;
export type UserRole = (typeof USER_ROLES)[number];

export interface LoginRequest {
  username: string;
  password: string;
}

// The raw backend response to `POST /auth/login`. This shape only ever
// exists server-side (inside the Next.js Route Handler that calls the
// backend) — the `access_token` must never be forwarded to client-side JS.
export interface BackendLoginResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  user_id: string;
}

// What the Next.js `/api/auth/login` Route Handler returns to the browser
// after setting the httpOnly cookie — non-sensitive fields only.
export interface ClientLoginResult {
  role: UserRole;
  user_id: string;
}

// `GET /auth/me` response — the authenticated user's profile, used to seed
// the server-rendered `AuthProvider`.
export interface CurrentUser {
  user_id: string;
  username: string;
  email: string;
  role: UserRole;
  full_name: string;
}

// ── `backend/api/routes/alerts.py`, `backend/api/routes/audit.py`,
// `backend/api/routes/dashboard.py` (ROADMAP Phase 14) ──────────────────
//
// Shapes mirrored 1:1 from those routes' Pydantic response models — do not
// invent fields the backend doesn't actually return. `db/enums.py`'s
// controlled vocabularies (`DetectionType`, `Priority`, `RiskLevel`) are
// typed as plain `string` here rather than re-declared string-literal
// unions: the backend routes accept/return raw `str(...)`-serialized enum
// values, and duplicating the enum member list here would just be a second
// place for it to drift out of sync with `db/enums.py`.

export interface AlertListItem {
  alert_id: string;
  primary_account_id: string;
  detection_type: string;
  risk_score: number;
  priority: string;
  severity: string;
  status: string;
  created_at: string;
  case_id: string | null;
  assigned_to: string | null;
  assigned_to_name: string | null;
  case_status: string | null;
}

export interface AlertListResponse {
  items: AlertListItem[];
  total_count: number;
  limit: number;
  offset: number;
}

// Query params accepted by `GET /alerts` (`api.routes.alerts._AlertListParams`).
// Values are typed loosely (`string | number | boolean`) because this same
// shape is used both for typed calls from Server Components (e.g. `{limit: 25}`)
// and for passing an incoming Route Handler's `URLSearchParams` straight
// through — both serialize to the same query string either way.
export interface AlertListParams {
  status?: string;
  priority?: string;
  severity?: string;
  detection_type?: string;
  min_risk_score?: number | string;
  max_risk_score?: number | string;
  start?: string;
  end?: string;
  assigned_to?: string;
  unassigned_only?: boolean | string;
  sort?: string;
  limit?: number | string;
  offset?: number | string;
}

export interface InvestigatorWorkloadItem {
  user_id: string;
  full_name: string;
  open_case_count: number;
}

export interface WorkloadResponse {
  investigators: InvestigatorWorkloadItem[];
}

export interface AssignAlertRequest {
  investigator_id: string;
}

export interface AssignAlertResponse {
  alert_id: string;
  case_id: string;
  case_status: string;
  assigned_to: string | null;
}

export interface AuditLogItem {
  id: number;
  actor_type: string;
  actor_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  case_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditLogListResponse {
  items: AuditLogItem[];
  total_count: number;
  limit: number;
  offset: number;
}

// Query params accepted by `GET /audit-log` (`api.routes.audit._AuditLogParams`).
// `action` is `list[str] | None` server-side (repeated `?action=` query
// params filtered as an allowlist, e.g. the notification bell's curated
// feed) — kept as a real array here, unlike the loosely-typed numeric/bool
// fields above, since a plain `String(value)` join would silently produce
// the wrong query string shape.
export interface AuditLogParams {
  case_id?: string;
  actor_id?: string;
  action?: string[];
  since?: string;
  limit?: number | string;
  offset?: number | string;
}

export interface AlertsOverTimePoint {
  date: string;
  count: number;
}

export interface DashboardSummaryResponse {
  active_alert_count: number;
  open_case_count: number;
  avg_risk_score: number | null;
  severity_breakdown: Record<string, number>;
  alerts_over_time: AlertsOverTimePoint[];
  window_days: number;
}

// ── `backend/api/routes/cases.py::GET /cases` (ROADMAP Phase 15) ──────────
//
// Role-scoped case list — distinct from `GET /alerts` above (system-wide).
// `status`/`priority` are typed as plain `string` here, same convention as
// `AlertListItem` above: the backend's `db.enums.CaseStatus`/`Priority` are
// the real source of truth, duplicating their member lists as a TS union
// here would just be a second place for it to drift.

export interface CaseListItem {
  case_id: string;
  primary_account_id: string;
  status: string;
  priority: string;
  assigned_to: string | null;
  updated_at: string;
}

export interface CaseListResponse {
  items: CaseListItem[];
  total_count: number;
  limit: number;
  offset: number;
}

// Query params accepted by `GET /cases` (`api.routes.cases._CaseListParams`).
export interface CaseListParams {
  status?: string;
  priority?: string;
  sort?: string;
  limit?: number | string;
  offset?: number | string;
}

// ── `backend/api/routes/cases.py`, `backend/api/routes/l2.py` (ROADMAP
// Phase 16, L1 Triage) ──────────────────────────────────────────────────
//
// Shapes mirrored 1:1 from those routes' Pydantic response models — same
// "backend enum -> plain `string`" convention as above, do not invent
// fields the backend doesn't actually return. `notes` lives in `l2.py` (a
// separate router file, same `/cases` prefix) but is an L1 feature per
// `FRONTEND_PLAN.md` §3.3. Pattern-explanation is explicitly Phase 17
// scope per `docs/FRONTEND_ROADMAP.md`'s Phase 16 checklist — not built
// here.

export interface AlertSummaryItem {
  alert_id: string;
  detection_type: string;
  primary_account_id: string;
  account_ids: string[];
  score: number;
  risk_score: number;
  severity: string;
  priority: string;
  confidence: string | null;
  status: string;
  rule_ids: string[] | null;
  created_at: string;
  last_seen_at: string;
}

export interface SiblingAccount {
  account_id: string;
  account_type: string;
  bank_name: string | null;
  branch_city: string | null;
  status: string;
  current_risk_score: number | null;
}

export interface CustomerSnapshotResponse {
  account_id: string;
  customer_id: string | null;
  name: string | null;
  entity_type: string | null;
  kyc_status: string | null;
  edd_status: string | null;
  pep_status: boolean | null;
  sanction_status: boolean | null;
  risk_rating: string | null;
  occupation: string | null;
  declared_annual_income: number | null;
  income_bracket: string | null;
  sibling_accounts: SiblingAccount[];
}

export interface GeoRiskResponse {
  account_id: string;
  branch_city: string | null;
  bank_name: string | null;
  bank_id: string | null;
  counterparty_bank_count: number;
  counterparty_banks: string[];
  counterparty_city_count: number;
  counterparty_cities: string[];
}

export interface TransactionSummaryResponse {
  account_id: string;
  total_in: number;
  total_out: number;
  txn_count: number;
  counterparty_count: number;
  channel_breakdown: Record<string, number>;
}

export interface TransactionPurposeItem {
  txn_id: string;
  timestamp: string;
  direction: "in" | "out";
  counterparty_account_id: string;
  amount: number;
  channel: string;
  purpose: string | null;
  narration: string | null;
}

export interface TransactionPurposeResponse {
  account_id: string;
  transactions: TransactionPurposeItem[];
  purpose_distribution: Record<string, number>;
}

export interface RiskTrendPoint {
  alert_id: string;
  created_at: string;
  risk_score: number;
}

export interface PreviousAlertsResponse {
  account_id: string;
  total_prior_alerts: number;
  prior_sar_count: number;
  prior_false_positive_count: number;
  prior_monitoring_count: number;
  risk_trend: RiskTrendPoint[];
}

export interface MoneyFlowNode {
  account_id: string;
  total_amount: number;
  txn_count: number;
  pct_of_total: number;
}

export interface MoneyFlowResponse {
  center: string;
  sources: MoneyFlowNode[];
  beneficiaries: MoneyFlowNode[];
}

export interface NetworkRiskResponse {
  case_id: string;
  network_risk_score: number | null;
  network_risk_reasons: Record<string, unknown> | null;
}

export interface SimilarCaseItem {
  case_id: string;
  similarity: number;
  typology: string | null;
  outcome: string | null;
  computed_at: string;
}

export interface SimilarCasesResponse {
  case_id: string;
  similar_cases: SimilarCaseItem[];
}

export interface ExplanationResponse {
  account_id: string;
  explanation: string;
  cached: boolean;
  model: string;
  generated_at: string;
}

export type DecisionValue = "close_fp" | "request_info" | "escalate";

export interface DecisionRequest {
  decision: DecisionValue;
  reason: string;
  note?: string;
}

export interface DecisionResponse {
  case_id: string;
  status: string;
  resolution: string | null;
}

export interface NoteCreateRequest {
  body: string;
}

export interface NoteItem {
  note_id: string;
  case_id: string;
  author_id: string | null;
  source: string;
  body: string;
  created_at: string;
}
