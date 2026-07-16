/**
 * `db/enums.py::Channel` -> plain-language label, for the L2 Investigation
 * Graph's and Transaction Explorer's channel filter checkboxes (ROADMAP
 * Phase 17). Extend alongside that enum, not independently — same
 * "duplicating an enum member list here would just be a second place for it
 * to drift" reasoning `lib/api/types.ts` already documents for every other
 * backend controlled vocabulary in this app.
 */
export interface ChannelOption {
  value: string;
  label: string;
}

export const CHANNEL_OPTIONS: ChannelOption[] = [
  { value: "UPI", label: "UPI" },
  { value: "NEFT", label: "NEFT" },
  { value: "RTGS", label: "RTGS" },
  { value: "IMPS", label: "IMPS" },
  { value: "net_banking", label: "Net Banking" },
  { value: "mobile_app", label: "Mobile App" },
  { value: "ATM", label: "ATM" },
  { value: "branch_cash", label: "Branch Cash" },
  { value: "cheque", label: "Cheque" },
  { value: "unknown", label: "Unknown" },
];

// `RoleClassifier` (`detection/scoring/ensemble.py`) only ever emits these
// four — the graph's role filter checkboxes, not a general role registry.
export const GRAPH_ROLE_OPTIONS: ChannelOption[] = [
  { value: "SOURCE", label: "Source" },
  { value: "MULE", label: "Mule" },
  { value: "SINK", label: "Sink" },
  { value: "NORMAL", label: "Normal" },
];
