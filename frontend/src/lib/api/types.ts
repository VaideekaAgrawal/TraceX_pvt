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
  // Nullable — some prior alerts never became a case (`investigation/
  // previous_alerts.py`'s own documented behavior). `null` rows are not
  // clickable in `previous-alerts.tsx`.
  case_id: string | null;
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

// `backend/api/routes/l2.py::GraphExplanationResponse` — AI narrative of the
// Investigation Graph (source/mule/sink roles, cycles, flow concentration),
// scoped to `account_id` like `ExplanationResponse` above (one explanation
// per account per case), not per-alert like `PatternExplanationResponse`
// below.
export interface GraphExplanationResponse {
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

// ── `backend/api/routes/l2.py` (ROADMAP Phase 17, L2 Deep Investigation —
// graph, timeline, transaction search, profile, behavior) ─────────────────
//
// Same "backend enum -> plain `string`" convention as the L1 types above.
// `GraphNode.role` is documented as exactly `"SOURCE" | "SINK" | "MULE" |
// "NORMAL"` by `detection/scoring/ensemble.py::RoleClassifier` (with a
// theoretical `"UNKNOWN"` fallback in `investigation/graph_filters.py` for a
// node `RoleClassifier` never scored) — kept as plain `string` anyway,
// matching this file's own stated rationale for every other backend-enum
// field, rather than special-casing this one field as a literal union.

export interface GraphNode {
  account_id: string;
  branch_city: string | null;
  role: string;
  role_confidence: number;
  current_risk_score: number | null;
  has_prior_sar: boolean;
  hop_distance: number | null;
}

export interface GraphEdge {
  txn_id: string;
  source_account: string;
  dest_account: string;
  amount: number;
  timestamp: string;
  channel: string;
  is_laundering: boolean;
  from_bank: string | null;
  to_bank: string | null;
}

export interface NHopGraphResponse {
  center: string;
  radius: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// Query params accepted by `GET /cases/{case_id}/accounts/{account_id}/graph`
// (`api.routes.l2.get_account_graph`). `channels`/`roles` are real arrays
// (repeated query params server-side), same convention as `AuditLogParams.
// action` above — a plain `String(value)` join would produce the wrong
// query string shape for these.
export interface GraphQueryParams {
  radius?: number;
  suspicious_only?: boolean;
  min_risk_score?: number;
  min_amount?: number;
  max_amount?: number;
  start?: string;
  end?: string;
  channels?: string[];
  direction?: "in" | "out";
  roles?: string[];
  prior_sar_only?: boolean;
}

export interface TimelineEventItem {
  txn_id: string;
  timestamp: string;
  direction: "in" | "out";
  counterparty_account_id: string;
  amount: number;
  channel: string;
  is_laundering: boolean;
}

export interface TimelineResponse {
  account_id: string;
  events: TimelineEventItem[];
}

export interface TimelineQueryParams {
  start?: string;
  end?: string;
}

export interface TransactionSearchItem {
  txn_id: string;
  timestamp: string;
  amount: number;
  channel: string;
  txn_type: string;
  source_account: string;
  dest_account: string;
  source_branch_city: string | null;
  dest_branch_city: string | null;
  source_account_type: string | null;
  dest_account_type: string | null;
  direction: "in" | "out" | null;
  is_laundering: boolean;
}

export interface TransactionSearchResponse {
  items: TransactionSearchItem[];
  total_count: number;
  limit: number;
  offset: number;
}

// Query params shared by both `GET /cases/{case_id}/transactions/search`
// (case-wide) and `GET /cases/{case_id}/accounts/{account_id}/transactions/
// search` (account-scoped) — mirrors `api.routes.l2._TransactionSearchParams`
// exactly. `sort` is typed as plain `string` (not the 4-member literal
// union) for the same "unrecognized value falls back silently server-side,
// not a 400" reason `l2.py`'s own docstring gives — a client typo here
// degrades to the default sort, it doesn't need a TS-level guarantee.
export interface TransactionSearchParams {
  min_amount?: number;
  max_amount?: number;
  start?: string;
  end?: string;
  channels?: string[];
  direction?: "in" | "out";
  txn_type?: string;
  limit?: number;
  offset?: number;
  sort?: string;
}

export interface CustomerProfileResponse {
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
  employer: string | null;
  declared_annual_income: number | null;
  income_bracket: string | null;
  account_type: string | null;
  bank_name: string | null;
  branch_city: string | null;
  account_status: string | null;
  kyc_tier: string | null;
  opening_date: string | null;
  current_risk_score: number | null;
  expected_monthly_volume: number | null;
  actual_monthly_volume_avg: number | null;
  expected_vs_actual_variance_ratio: number | null;
  prior_sar_count: number;
  total_prior_alerts: number;
  sibling_accounts: SiblingAccount[];
  // Always `["beneficial_owner", "linked_cards", "linked_loans",
  // "linked_deposits", "risk_score_trend"]` today (unconditional documented
  // schema gaps, not per-account variance) — rendered explicitly as "Not
  // available" rows, per `docs/FRONTEND_ROADMAP.md` Phase 17 scope, rather
  // than hidden/blank.
  omitted_fields: string[];
}

export interface MonthlyTotalItem {
  month: string;
  total_in: number;
  total_out: number;
  total: number;
  txn_count: number;
}

export interface CashDepositMonthItem {
  month: string;
  cash_deposit_total: number;
  txn_count: number;
}

export interface TransferMonthItem {
  month: string;
  transfer_total: number;
  txn_count: number;
}

export interface DormancyReactivationEvent {
  gap_start: string;
  gap_end: string;
  gap_days: number;
  burst_txn_count: number;
}

export interface DormancyReactivationResult {
  reactivation_detected: boolean;
  events: DormancyReactivationEvent[];
}

export interface VelocityIncreaseResult {
  recent_avg_weekly_txn_count: number;
  baseline_avg_weekly_txn_count: number;
  ratio: number | null;
  velocity_increase_detected: boolean;
}

export interface BehaviorAnalysisResponse {
  account_id: string;
  monthly_totals: MonthlyTotalItem[];
  cash_deposit_trend: CashDepositMonthItem[];
  transfer_trend: TransferMonthItem[];
  dormancy_reactivation: DormancyReactivationResult;
  velocity_increase: VelocityIncreaseResult;
  // Always `["salary_mismatch", "seasonal_trends"]` today — rendered as
  // "Not yet available," matching `CustomerProfileResponse.omitted_fields`'s
  // treatment (same honesty pattern, not a second UI convention).
  deferred: string[];
}

// ── `backend/api/routes/l2.py` (ROADMAP Phase 18 — Relationship Explorer,
// Pattern Explanation, Evidence Management) ────────────────────────────
//
// Same "backend enum -> plain `string`" convention as the rest of this
// file. `RelationshipEdge.confidence` is deliberately a raw number (0.95
// for an exact PAN match down to 0.25 for a shared branch city, per
// `investigation/relationship_discovery.py`'s documented confidence
// scheme) — the ROADMAP explicitly calls out that this number must be
// shown per-edge, not collapsed into a boolean "related" flag.

export interface RelationshipNode {
  customer_id: string;
  name: string | null;
  // The single most important visual distinction in this graph — a
  // customer surfaced here with `in_case_scope: false` has NO direct
  // transaction link to this case, only a shared attribute (PAN, name,
  // income bracket, branch city). See `SYSTEM_DEVELOPMENT_PLAN.md` §4.2.
  in_case_scope: boolean;
}

export interface RelationshipEdge {
  id: number;
  entity_a: string;
  entity_b: string;
  shared_attribute: string;
  confidence: number;
  method: string;
  discovered_at: string;
}

export interface RelationshipGraphResponse {
  case_id: string;
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
}

export interface PatternExplanationResponse {
  alert_id: string;
  explanation: string;
  cached: boolean;
  model: string;
  generated_at: string;
  rule_anchors: { detection_type?: string; rule_ids?: string[]; alert_id?: string } | null;
  pattern_signature: string;
}

// `db/enums.py::EvidenceType` — mirrored as a literal union (unlike most
// other backend enums in this file) because the create form below needs to
// exhaustively switch on it to decide which fields to show; a plain
// `string` would let a typo silently fall through to "no extra fields"
// instead of a compile error.
export const EVIDENCE_TYPES = [
  "TRANSACTION",
  "ACCOUNT",
  "GRAPH_SNAPSHOT",
  "DOCUMENT",
  "PATTERN",
  "NOTE_REF",
] as const;
export type EvidenceType = (typeof EVIDENCE_TYPES)[number];

export interface EvidenceCreateRequest {
  type: EvidenceType;
  ref_id?: string | null;
  label?: string | null;
  payload?: Record<string, unknown> | null;
  // Plain text reference/path string — explicitly NOT a file uploader, no
  // upload backend exists anywhere in this codebase (ROADMAP Phase 18
  // scope note).
  file_path?: string | null;
}

export interface EvidenceItem {
  evidence_id: string;
  case_id: string;
  type: string;
  ref_id: string | null;
  label: string | null;
  payload: Record<string, unknown> | null;
  file_path: string | null;
  pinned: boolean;
  added_by: string;
  added_at: string;
}
