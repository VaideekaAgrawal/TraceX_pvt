export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API error ${res.status}: ${text}`);
  }
  return res.json();
}

// ── Types ──────────────────────────────────────────────────────────────────
export interface OverviewData {
  stats: { num_nodes: number; num_edges: number; num_components: number; density: number; avg_in_degree: number; avg_out_degree: number };
  risk_distribution: Record<string, number>;
  role_distribution: Record<string, number>;
  top_alerts: Alert[];
  pattern_counts: Record<string, number>;
  total_flagged: number;
  total_anomalies: number;
  fraud_metrics: Record<string, number | number[]>;
  total_amount: number;
  avg_risk: number;
}

export interface Alert {
  account_id: string;
  risk_score: number;
  risk_level: string;
  risk_color: string;
  role: string;
  branch_city: string;
  account_type: string;
}

export interface Account {
  account_id: string;
  account_type: string;
  branch_city: string;
  occupation: string;
  income_bracket: string;
  declared_annual_income: number;
  total_in_flow: number;
  total_out_flow: number;
  txn_count: number;
  risk_score: number;
  risk_level: string;
  risk_color: string;
  role: string;
  role_confidence: number;
  anomaly_score: number;
}

export interface AccountDetail {
  account: Record<string, string | number>;
  risk_score: number;
  risk_level: string;
  risk_color: string;
  role: string;
  role_confidence: number;
  anomaly_score: number;
  fraud_probability: number;
  features: Record<string, number>;
  confidence: { level: string; count: number; indicators: string[] };
  priority: string;
  total_amount: number;
  counterparties: number;
  recent_transactions: Transaction[];
}

export interface Transaction {
  txn_id: string;
  timestamp: string;
  source_account: string;
  dest_account: string;
  amount: number;
  channel: string;
  txn_type?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  center?: string;
}

export interface GraphNode {
  id: string;
  risk_score: number;
  risk_level: string;
  risk_color: string;
  role: string;
  is_center?: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  amount: number;
  channel: string;
  timestamp: string;
}

export interface AnomalyData {
  anomaly_scores: { account_id: string; anomaly_score: number }[];
  feature_importance: Record<string, number>;
  investigation_queue: InvestigationItem[];
  speed_alerts: SpeedAlert[];
}

export interface InvestigationItem {
  account_id: string;
  risk_score: number;
  risk_level: string;
  risk_color: string;
  role: string;
  priority: string;
  confidence_level: string;
  confidence_count: number;
  indicators: string[];
  anomaly_score: number;
  fraud_probability: number;
  total_amount: number;
  branch_city: string;
}

export interface SpeedAlert {
  accounts: string[];
  category: string;
  label: string;
  color: string;
  avg_minutes_per_hop: number;
  total_minutes: number;
  hops: number;
  total_amount: number;
}

export interface PatternData {
  patterns: Record<string, unknown>;
  flagged_accounts: string[];
}

export interface ProfileData {
  scatter_data: { account_id: string; declared_income: number; actual_volume: number; occupation: string; income_bracket: string; ratio: number }[];
  mismatches: Record<string, unknown>[];
}

export interface ChannelData {
  summary: { channel: string; count: number; total_amount: number; avg_amount: number; max_amount: number }[];
  sankey: { source_type: string; channel: string; dest_type: string; count: number; total: number }[];
  heatmap: { channel: string; hour: number; count: number }[];
  suspicious: { channel: string; count: number; total: number; unique_accounts: number }[];
}

export interface RLQueueItem {
  account_id: string;
  risk_score: number;
  risk_level: string;
  role: string;
  patterns: string[];
  anomaly_score: number;
  fraud_probability: number;
  total_amount: number;
  counterparties: number;
  channel_diversity: number;
  rl_expected_reward: number;
  rl_uncertainty: number;
  rl_ucb_score: number;
  rl_is_exploration: boolean;
}

export interface RLFeature {
  feature: string;
  weight: number;
}

export interface RLStats {
  total_feedback: number;
  tp_count: number;
  fp_count: number;
  learned_precision: number;
  top_learned_features: RLFeature[];
  exploration_coefficient: number;
  learning_status: string;
}

export interface RLQueueResponse {
  queue: RLQueueItem[];
  agent_stats: RLStats;
}

export interface RLFeedbackResponse {
  status: string;
  reward_applied: number;
  agent_stats: RLStats;
  top_learned_features: RLFeature[];
}

export interface RLWeightsResponse {
  weights: Record<string, number>;
  stats: RLStats;
  interpretation: string;
}

export interface RLSimulateResponse {
  steps_replayed: number;
  final_stats: RLStats;
  weight_evolution: { step: number; weights: RLFeature[]; precision: number }[];
  message: string;
}

export interface DashboardLive {
  transactions_last_60s: number;
  alerts_last_60s: number;
  highest_risk_account_today: { account_id: string; score: number } | null;
  event_bus_queue_depth: number;
  dlq_depth: number;
}

export interface DailySummaryAlert {
  alert_id: string;
  account_id: string;
  account_ids: string[];
  pattern_type: string;
  risk_score: number;
  risk_level: string;
  severity: string;
  status: string;
  detected_at: string;
  last_seen_at: string;
}

export interface DailySummary {
  run_date: string;
  run_at: string;
  new_alerts: DailySummaryAlert[];
  reactivated_alerts: DailySummaryAlert[];
  stale_alert_ids: string[];
  total_accounts_flagged: number;
  total_alerts_open: number;
  accounts_ingested: number;
  transactions_ingested: number;
}

// ── Rule Engine ──────────────────────────────────────────────────────────

export interface PrimitiveSpec {
  params: Record<string, string>; // param name -> type spec, e.g. "int" | "float" | "str" | "enum:a,b"
  defaults: Record<string, string | number | boolean>;
  ceilings: Record<string, number>;
}

export interface RuleConditionDraft {
  primitive: string;
  params: Record<string, string | number | boolean>;
  negate: boolean;
}

export interface RuleJsonDraft {
  combinator: "AND" | "OR";
  conditions: RuleConditionDraft[];
}

export interface RuleDraft {
  rule_id: string;
  name: string;
  description?: string;
  detection_type: string;
  severity: string;
  rule_json: RuleJsonDraft;
  enabled?: boolean;
}

export interface DetectionRule extends RuleDraft {
  enabled: boolean;
  is_builtin: boolean;
  version: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface RuleDryRunResult {
  matched_count: number;
  sample_matches: Array<{
    account_ids: string[];
    score: number;
    severity: string;
    indicators: string[];
  }>;
  newly_flagged_accounts: string[];
}

export interface GraphValidationStats {
  nodes: number;
  edges: number;
  layering_chains_found: number;
  shortest_chain: number;
  longest_chain: number;
  round_trip_cycles_found: number;
  shortest_cycle: number;
  longest_cycle: number;
  structuring_accounts: number;
  dormant_activations: number;
  profile_mismatches: number;
  algorithm_runtime_ms: Record<string, number>;
  centrality_cache_hit: boolean;
  false_positive_gate: {
    single_signal_accounts: number;
    multi_signal_accounts: number;
    accounts_promoted_to_P1: number;
  };
}

export interface GraphValidationResponse {
  account_id: string;
  graph: GraphData;
  graph_validation: GraphValidationStats;
  why_flagged: string;
}

export interface AccountExplanation {
  account_id: string;
  explanation: string;
  cached: boolean;
}

export interface FundTrailResult {
  account_id?: string;
  component_size?: number;
  trail_count?: number;
  trails?: Record<string, unknown>[][];
  error?: string;
}

export interface AccompliceResult {
  start_node: string;
  accomplices: { account_id: string; visit_probability: number; risk_score: number; risk_level: string; role: string }[];
}

export interface EvidenceResult {
  case_id: string;
  summary: Record<string, unknown>;
  pdf_base64: string;
  json_data: string;
}

// ── API Functions ──────────────────────────────────────────────────────────
export const api = {
  getOverview: () => fetchApi<OverviewData>("/api/overview"),
  getAccounts: () => fetchApi<Account[]>("/api/accounts"),
  getAccountDetail: (id: string) => fetchApi<AccountDetail>(`/api/accounts/${id}`),
  getGraph: (maxNodes = 100) => fetchApi<GraphData>(`/api/graph?max_nodes=${maxNodes}`),
  getEgoGraph: (id: string, radius = 2) => fetchApi<GraphData>(`/api/graph/ego/${id}?radius=${radius}`),
  getFundTrail: (account_id: string, direction = "both", max_depth = 5) =>
    fetchApi<FundTrailResult>("/api/graph/fund-trail", { method: "POST", body: JSON.stringify({ account_id, direction, max_depth }) }),
  getRandomWalk: (start_node: string) =>
    fetchApi<AccompliceResult>("/api/graph/random-walk", { method: "POST", body: JSON.stringify({ start_node }) }),
  getAnomaly: () => fetchApi<AnomalyData>("/api/anomaly"),
  getPatterns: () => fetchApi<PatternData>("/api/patterns"),
  getFirstSuspicious: (id: string) => fetchApi<{ found: boolean; data?: Record<string, unknown> }>(`/api/patterns/first-suspicious/${id}`),
  getProfile: () => fetchApi<ProfileData>("/api/profile"),
  getPeerGroup: (id: string) => fetchApi<Record<string, unknown>>(`/api/profile/${id}`),
  getChannels: () => fetchApi<ChannelData>("/api/channels"),
  generateEvidence: (case_id: string, account_ids: string[], pattern_type: string, case_notes: string) =>
    fetchApi<EvidenceResult>("/api/evidence/generate", { method: "POST", body: JSON.stringify({ case_id, account_ids, pattern_type, case_notes }) }),
  getTransactions: (limit = 100, offset = 0) =>
    fetchApi<{ total: number; transactions: Transaction[] }>(`/api/transactions?limit=${limit}&offset=${offset}`),
  getHealth: () => fetchApi<{ status: string; initialized: boolean; accounts: number; transactions: number }>("/api/health"),

  // Initialize / re-load system with a dataset
  initSystem: (source: string, filepath: string, maxRows?: number) =>
    fetchApi<Record<string, unknown>>("/api/init", {
      method: "POST",
      body: JSON.stringify({ source, filepath, max_rows: maxRows }),
    }),

  // Rebuild graph + detection from existing DB data (no file needed)
  refreshSystem: () =>
    fetchApi<Record<string, unknown>>("/api/refresh", { method: "POST" }),

  // ── Production Endpoints (EOD Ingestion & Filters) ──
  ingestEOD: (filepath: string, date?: string, force = false) =>
    fetchApi<Record<string, unknown>>("/api/ingest", {
      method: "POST",
      body: JSON.stringify({ filepath, date, force }),
    }),

  // File upload ingestion — accepts a File object from the browser
  ingestUpload: async (file: File, date?: string, force = false): Promise<Record<string, unknown>> => {
    const formData = new FormData();
    formData.append("file", file);
    if (date) formData.append("date", date);
    if (force) formData.append("force", "true");

    const res = await fetch(`${API_BASE}/api/ingest/upload`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API error ${res.status}: ${text}`);
    }
    return res.json();
  },

  getIngestionStatus: () => fetchApi<Record<string, unknown>>("/api/ingest/status"),
  getIngestionHistory: () => fetchApi<Record<string, unknown>[]>("/api/ingest/history"),

  // Filtered graph with multi-param support
  getGraphFiltered: (params: {
    risk_min?: number;
    risk_max?: number;
    pattern?: string;
    since?: string;
    until?: string;
    max_nodes?: number;
    role?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params.risk_min !== undefined) qs.set("risk_min", String(params.risk_min));
    if (params.risk_max !== undefined) qs.set("risk_max", String(params.risk_max));
    if (params.pattern) qs.set("pattern", params.pattern);
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    if (params.max_nodes !== undefined) qs.set("max_nodes", String(params.max_nodes));
    if (params.role) qs.set("role", params.role);
    return fetchApi<GraphData & { meta?: Record<string, number> }>(`/api/graph/filtered?${qs.toString()}`);
  },

  // Pattern-specific subgraph (Neo4j-style visualization of flagged accounts)
  getPatternGraph: (patternType: string, maxNodes = 60) =>
    fetchApi<GraphData & { pattern_type: string; count: number; total_flagged_accounts: number }>(
      `/api/graph/pattern/${patternType}?max_nodes=${maxNodes}`
    ),

  // Filtered transactions with pagination
  getTransactionsFiltered: (params: {
    account_id?: string;
    channel?: string;
    min_amount?: number;
    max_amount?: number;
    since?: string;
    until?: string;
    is_laundering?: number;
    risk_level?: string;
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_order?: string;
  }) => {
    const qs = new URLSearchParams();
    if (params.account_id) qs.set("account_id", params.account_id);
    if (params.channel) qs.set("channel", params.channel);
    if (params.min_amount !== undefined) qs.set("min_amount", String(params.min_amount));
    if (params.max_amount !== undefined) qs.set("max_amount", String(params.max_amount));
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    if (params.is_laundering !== undefined) qs.set("is_laundering", String(params.is_laundering));
    if (params.risk_level) qs.set("risk_level", params.risk_level);
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    if (params.sort_by) qs.set("sort_by", params.sort_by);
    if (params.sort_order) qs.set("sort_order", params.sort_order);
    return fetchApi<{ total: number; limit: number; offset: number; transactions: Transaction[] }>(
      `/api/transactions/filtered?${qs.toString()}`
    );
  },

  getDbStats: () => fetchApi<{ status: string; accounts: number; transactions: number }>("/api/db/stats"),

  // ── Case Management ──
  getCases: () => fetchApi<InvestigationCase[]>("/api/cases"),
  getCase: (id: string) => fetchApi<InvestigationCase>(`/api/cases/${id}`),
  createCase: (data: CaseCreatePayload) =>
    fetchApi<InvestigationCase>("/api/cases", { method: "POST", body: JSON.stringify(data) }),
  updateCaseStatus: (id: string, status: string, notes: string) =>
    fetchApi<InvestigationCase>(`/api/cases/${id}/status`, {
      method: "PUT",
      body: JSON.stringify({ status, notes }),
    }),

  getAccountExplanation: (id: string, force = false) =>
    fetchApi<AccountExplanation>(`/api/explain/account/${id}?force=${force}`),

  getGraphValidation: (accountId: string) =>
    fetchApi<GraphValidationResponse>(`/api/graph/validate/${accountId}`),

  getDashboardLive: () => fetchApi<DashboardLive>("/api/dashboard/live"),
  getDailySummary: (date?: string) =>
    fetchApi<DailySummary>(`/api/daily-summary${date ? `?date=${date}` : ""}`),

  // ── Rule Engine ──
  getRulePrimitives: () => fetchApi<Record<string, PrimitiveSpec>>("/api/rules/primitives"),
  getRules: () => fetchApi<DetectionRule[]>("/api/rules"),
  getRule: (ruleId: string) => fetchApi<DetectionRule>(`/api/rules/${ruleId}`),
  createRule: (rule: RuleDraft) =>
    fetchApi<DetectionRule>("/api/rules", { method: "POST", body: JSON.stringify(rule) }),
  updateRule: (ruleId: string, updates: Partial<RuleDraft>) =>
    fetchApi<DetectionRule>(`/api/rules/${ruleId}`, { method: "PUT", body: JSON.stringify(updates) }),
  deleteRule: (ruleId: string) => fetchApi<{ status: string }>(`/api/rules/${ruleId}`, { method: "DELETE" }),
  enableRule: (ruleId: string) => fetchApi<DetectionRule>(`/api/rules/${ruleId}/enable`, { method: "POST" }),
  disableRule: (ruleId: string) => fetchApi<DetectionRule>(`/api/rules/${ruleId}/disable`, { method: "POST" }),
  dryRunRule: (detection_type: string, severity: string, rule_json: RuleJsonDraft) =>
    fetchApi<RuleDryRunResult>("/api/rules/dry-run", {
      method: "POST",
      body: JSON.stringify({ detection_type, severity, rule_json }),
    }),

  // ── Real-Time Fraud Detection Demo ──
  startRealtimeDemo: () =>
    fetchApi<{ status: string; total: number }>("/api/realtime/start", { method: "POST" }),
  getRealtimeStatus: () =>
    fetchApi<{ running: boolean; processed: number; total: number }>("/api/realtime/status"),

  // ── RL — Adaptive Investigation Queue (LinUCB contextual bandit) ──
  getRLQueue: () => fetchApi<RLQueueResponse>("/api/rl/queue"),
  submitRLFeedback: (account_id: string, is_true_positive: boolean) =>
    fetchApi<RLFeedbackResponse>("/api/rl/feedback", {
      method: "POST",
      body: JSON.stringify({ account_id, is_true_positive }),
    }),
  getRLWeights: () => fetchApi<RLWeightsResponse>("/api/rl/weights"),
  simulateRL: (steps = 30, scenario = "balanced") =>
    fetchApi<RLSimulateResponse>("/api/rl/simulate", {
      method: "POST",
      body: JSON.stringify({ steps, scenario }),
    }),
};

// ── Case Management Types ──────────────────────────────────────────────────

export interface InvestigationCase {
  case_id: string;
  account_ids: string[];
  risk_scores: Record<string, number>;
  pattern_type: string;
  notes: string;
  investigator: string;
  status: string;
  graph_snapshot: string;
  str_reference: string;
  created_at: string;
  updated_at: string;
}

export interface CaseCreatePayload {
  case_id: string;
  account_ids: string[];
  risk_scores?: Record<string, number>;
  pattern_type?: string;
  notes?: string;
  investigator?: string;
  graph_snapshot?: string;
  str_reference?: string;
}

// ── Real-Time Fraud Detection SSE Event Types ───────────────────────────────

export interface RealtimeTransactionPayload {
  timestamp: string;
  source_account: string;
  dest_account: string;
  amount: number;
  payment_format: string;
  new_accounts: number;
  alerts_generated: number;
  processed: number;
  total: number;
}

export interface RealtimeAlertPayload {
  pattern_type: string;
  count: number;
  source_account: string;
  dest_account: string;
  amount: number;
  timestamp: string;
  processed: number;
  total: number;
}

export interface RealtimeDonePayload {
  processed: number;
  error?: string;
}

export type RealtimeSSEEvent =
  | { topic: "realtime.transaction"; data: RealtimeTransactionPayload; timestamp: string }
  | { topic: "realtime.alert"; data: RealtimeAlertPayload; timestamp: string }
  | { topic: "realtime.done"; data: RealtimeDonePayload; timestamp: string };
