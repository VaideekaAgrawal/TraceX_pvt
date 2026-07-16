"use client";

import type { Core, ElementDefinition, NodeSingular, StylesheetJsonBlock } from "cytoscape";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import "@/components/workspace/deep/graph-theme.css";
import { readGraphTheme, roleColor, roleLabel, type GraphTheme } from "@/components/workspace/deep/graph-theme";
import { formatRiskScore } from "@/components/dashboard/format";
import { CHANNEL_OPTIONS, GRAPH_ROLE_OPTIONS } from "@/lib/workspace/channel-options";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { GraphNode, NHopGraphResponse } from "@/lib/api/types";

const MAX_RADIUS = 4;
const MIN_RADIUS = 1;
// Nodes with no recorded risk score get a fixed, low-visual-weight default
// size rather than `mapData` choking on `null` — "null-safe" per the
// dataviz guidance (a genuinely unscored node shouldn't visually dominate).
const DEFAULT_RISK = 15;

interface GraphFilterState {
  radius: number;
  suspiciousOnly: boolean;
  minRiskScore: string;
  minAmount: string;
  maxAmount: string;
  start: string;
  end: string;
  channels: string[];
  direction: "" | "in" | "out";
  roles: string[];
  priorSarOnly: boolean;
}

const DEFAULT_FILTERS: GraphFilterState = {
  radius: 2,
  suspiciousOnly: false,
  minRiskScore: "",
  minAmount: "",
  maxAmount: "",
  start: "",
  end: "",
  channels: [],
  direction: "",
  roles: [],
  priorSarOnly: false,
};

const ALL = "__all__";

function buildGraphUrl(caseId: string, accountId: string, filters: GraphFilterState): string {
  const qs = new URLSearchParams();
  qs.set("radius", String(filters.radius));
  if (filters.suspiciousOnly) qs.set("suspicious_only", "true");
  if (filters.minRiskScore) qs.set("min_risk_score", filters.minRiskScore);
  if (filters.minAmount) qs.set("min_amount", filters.minAmount);
  if (filters.maxAmount) qs.set("max_amount", filters.maxAmount);
  if (filters.start) qs.set("start", filters.start);
  if (filters.end) qs.set("end", filters.end);
  for (const c of filters.channels) qs.append("channels", c);
  if (filters.direction) qs.set("direction", filters.direction);
  for (const r of filters.roles) qs.append("roles", r);
  if (filters.priorSarOnly) qs.set("prior_sar_only", "true");
  return `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/graph?${qs.toString()}`;
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function buildElements(
  data: NHopGraphResponse,
  theme: GraphTheme,
  selectedTxnId: string | null,
  selectedNodeId: string | null,
): ElementDefinition[] {
  const nodes: ElementDefinition[] = data.nodes.map((n) => ({
    data: {
      id: n.account_id,
      label: truncate(n.account_id, 10),
      role: n.role,
      color: roleColor(theme, n.role),
      risk: n.current_risk_score ?? DEFAULT_RISK,
      hasPriorSar: n.has_prior_sar,
      isCenter: n.account_id === data.center,
      hop: n.hop_distance ?? 0,
      isSelected: n.account_id === selectedNodeId,
    },
  }));

  const maxAmount = data.edges.reduce((max, e) => Math.max(max, e.amount), 1);
  const edges: ElementDefinition[] = data.edges.map((e) => ({
    data: {
      id: e.txn_id,
      source: e.source_account,
      target: e.dest_account,
      amount: e.amount,
      // Log scale, per dataviz guidance — real transaction amounts span
      // orders of magnitude, a linear scale would make everything but the
      // single largest edge look identical.
      width: 1.5 + (Math.log10(e.amount + 1) / Math.log10(maxAmount + 1)) * 6,
      edgeColor: e.is_laundering ? theme.statusFlag : theme.edge,
      isLaundering: e.is_laundering,
      isSelected: e.txn_id === selectedTxnId,
    },
  }));

  return [...nodes, ...edges];
}

// Style values here (`mapData(...)`, `data(...)`) are cytoscape's own
// data-driven mapper syntax — strings, not the numeric-literal shape
// cytoscape's bundled types expect for these properties in `StylesheetCSS`,
// which is exactly what cytoscape's real style API accepts at runtime (see
// http://js.cytoscape.org/#style/mappers). Built as a loosely-typed literal
// and cast to `StylesheetJsonBlock[]` at the boundary, rather than fighting
// the upstream types for a shape they don't model.
function buildStylesheet(theme: GraphTheme): StylesheetJsonBlock[] {
  const rules: Array<{ selector: string; style: Record<string, unknown> }> = [
    {
      selector: "node",
      style: {
        "background-color": "data(color)",
        width: "mapData(risk, 0, 100, 22, 64)",
        height: "mapData(risk, 0, 100, 22, 64)",
        label: "data(label)",
        "font-size": 8,
        color: theme.label,
        "text-valign": "bottom",
        "text-margin-y": 4,
        "border-width": 1,
        "border-color": theme.edge,
        "overlay-opacity": 0,
      },
    },
    {
      selector: "node[?isCenter]",
      style: {
        "background-color": theme.centerFill,
        "border-width": 3,
        "border-color": theme.centerStroke,
      },
    },
    {
      selector: "node[?hasPriorSar]",
      style: {
        "border-width": 3,
        "border-color": theme.statusFlag,
      },
    },
    {
      selector: "node[?isSelected]",
      style: {
        "overlay-color": theme.selection,
        "overlay-opacity": 0.35,
        "overlay-padding": 6,
      },
    },
    {
      selector: "edge",
      style: {
        width: "data(width)",
        "line-color": "data(edgeColor)",
        "target-arrow-color": "data(edgeColor)",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.7,
        "curve-style": "bezier",
        opacity: 0.85,
        "overlay-opacity": 0,
      },
    },
    {
      selector: "edge[?isLaundering]",
      style: {
        "line-style": "dashed",
      },
    },
    {
      selector: "edge[?isSelected]",
      style: {
        "overlay-color": theme.selection,
        "overlay-opacity": 0.45,
        "overlay-padding": 4,
      },
    },
  ];
  return rules as unknown as StylesheetJsonBlock[];
}

/**
 * L2 §1 — Complete Investigation Graph. First real `cytoscape` consumer in
 * this app (ROADMAP Phase 17) — N-hop ego-graph around `accountId`, full
 * filter set wired to `GET .../graph`, `concentric` layout keyed on
 * `hop_distance` so the hop structure stays legible (center in the middle,
 * each hop a ring further out) rather than a generic force-directed layout
 * that would hide it.
 *
 * `selectedTxnId`/`onSelectTxn` are lifted to `deep-view.tsx` so a timeline
 * click highlights the matching edge here (and, the other direction,
 * clicking an edge here highlights its timeline row) — pure client-side
 * `txn_id` matching, per the designed data contract, no extra fetch.
 */
export function InvestigationGraphSection({
  caseId,
  accountId,
  selectedTxnId,
  onSelectTxn,
}: {
  caseId: string;
  accountId: string;
  selectedTxnId: string | null;
  onSelectTxn: (txnId: string | null) => void;
}) {
  const [filters, setFilters] = useState<GraphFilterState>(DEFAULT_FILTERS);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const url = useMemo(() => buildGraphUrl(caseId, accountId, filters), [caseId, accountId, filters]);
  const { data, loading, error } = useTriageFetch<NHopGraphResponse>(url);

  const theme = useMemo(() => readGraphTheme(), []);
  const selectedNodeId = selectedNode?.account_id ?? null;
  const elements = useMemo(
    () => (data ? buildElements(data, theme, selectedTxnId, selectedNodeId) : []),
    [data, theme, selectedTxnId, selectedNodeId],
  );
  const stylesheet = useMemo(() => buildStylesheet(theme), [theme]);

  const cyInstanceRef = useRef<Core | null>(null);
  const onSelectTxnRef = useRef(onSelectTxn);
  const nodesByIdRef = useRef<Map<string, GraphNode>>(new Map());

  useEffect(() => {
    onSelectTxnRef.current = onSelectTxn;
  }, [onSelectTxn]);

  useEffect(() => {
    nodesByIdRef.current = new Map((data?.nodes ?? []).map((n) => [n.account_id, n]));
  }, [data]);

  // Re-run the concentric layout only when a fresh graph arrives (new
  // `data`), not on every selection change — `cy={...}`'s callback fires on
  // every cytoscape update, so `cyInstanceRef` guards against re-attaching
  // click listeners more than once for the same instance.
  const handleCyInit = useCallback((cy: Core) => {
    if (cyInstanceRef.current === cy) return;
    cyInstanceRef.current = cy;
    cy.on("tap", "node", (evt) => {
      const id = evt.target.id();
      setSelectedNode(nodesByIdRef.current.get(id) ?? null);
    });
    cy.on("tap", "edge", (evt) => {
      const txnId = evt.target.id();
      onSelectTxnRef.current(txnId);
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) setSelectedNode(null);
    });
  }, []);

  useEffect(() => {
    const cy = cyInstanceRef.current;
    if (!cy || !data) return;
    cy.layout({
      name: "concentric",
      concentric: (node: NodeSingular) => 1000 - (Number(node.data("hop")) || 0) * 100,
      levelWidth: () => 1,
      minNodeSpacing: 45,
      animate: false,
      fit: true,
    }).run();
  }, [data]);

  function updateFilter<K extends keyof GraphFilterState>(key: K, value: GraphFilterState[K]) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function toggleListValue(key: "channels" | "roles", value: string, checked: boolean) {
    setFilters((prev) => ({
      ...prev,
      [key]: checked ? [...prev[key], value] : prev[key].filter((v) => v !== value),
    }));
  }

  const hasActiveFilters = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS);

  return (
    <TriageSection
      title="Complete Investigation Graph"
      description="N-hop ego-network around the primary account. Click a node for detail, click an edge to correlate with the timeline below."
      loading={loading}
      error={error}
      isEmpty={!!data && data.nodes.length === 0}
      emptyText="No graph data for this account at the current filters."
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 rounded-lg border p-3">
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex w-48 flex-col gap-1">
              <Label className="text-muted-foreground text-xs font-normal">
                Radius: {filters.radius} hop{filters.radius === 1 ? "" : "s"}
              </Label>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon-sm"
                  disabled={filters.radius <= MIN_RADIUS}
                  onClick={() => updateFilter("radius", Math.max(MIN_RADIUS, filters.radius - 1))}
                  title="Collapse one hop"
                >
                  −
                </Button>
                <Slider
                  min={MIN_RADIUS}
                  max={MAX_RADIUS}
                  step={1}
                  value={[filters.radius]}
                  onValueChange={(value) => updateFilter("radius", Array.isArray(value) ? value[0] : value)}
                  className="flex-1"
                />
                <Button
                  variant="outline"
                  size="icon-sm"
                  disabled={filters.radius >= MAX_RADIUS}
                  onClick={() => updateFilter("radius", Math.min(MAX_RADIUS, filters.radius + 1))}
                  title="Expand one hop"
                >
                  +
                </Button>
              </div>
            </div>

            <div className="flex w-56 flex-col gap-1">
              <Label className="text-muted-foreground text-xs font-normal">
                Min risk score: {filters.minRiskScore || "0"}
              </Label>
              <Slider
                min={0}
                max={100}
                step={1}
                value={[Number(filters.minRiskScore) || 0]}
                onValueChange={(value) =>
                  updateFilter("minRiskScore", String(Array.isArray(value) ? value[0] : value))
                }
              />
            </div>

            <Field label="Min amount">
              <Input
                type="number"
                inputMode="decimal"
                className="w-28"
                value={filters.minAmount}
                onChange={(e) => updateFilter("minAmount", e.target.value)}
              />
            </Field>
            <Field label="Max amount">
              <Input
                type="number"
                inputMode="decimal"
                className="w-28"
                value={filters.maxAmount}
                onChange={(e) => updateFilter("maxAmount", e.target.value)}
              />
            </Field>
            <Field label="From">
              <Input
                type="date"
                className="w-36"
                value={filters.start}
                onChange={(e) => updateFilter("start", e.target.value)}
              />
            </Field>
            <Field label="To">
              <Input
                type="date"
                className="w-36"
                value={filters.end}
                onChange={(e) => updateFilter("end", e.target.value)}
              />
            </Field>
            <Field label="Direction">
              <Select
                value={filters.direction || ALL}
                onValueChange={(value) =>
                  updateFilter("direction", value === ALL ? "" : (String(value) as "in" | "out"))
                }
              >
                <SelectTrigger size="sm" className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Any</SelectItem>
                  <SelectItem value="in">Inbound</SelectItem>
                  <SelectItem value="out">Outbound</SelectItem>
                </SelectContent>
              </Select>
            </Field>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-1.5">
              <Checkbox
                id={`graph-suspicious-${accountId}`}
                checked={filters.suspiciousOnly}
                onCheckedChange={(checked) => updateFilter("suspiciousOnly", !!checked)}
              />
              <Label htmlFor={`graph-suspicious-${accountId}`} className="text-sm font-normal">
                Suspicious transactions only
              </Label>
            </div>
            <div className="flex items-center gap-1.5">
              <Checkbox
                id={`graph-prior-sar-${accountId}`}
                checked={filters.priorSarOnly}
                onCheckedChange={(checked) => updateFilter("priorSarOnly", !!checked)}
              />
              <Label htmlFor={`graph-prior-sar-${accountId}`} className="text-sm font-normal">
                Prior SAR accounts only
              </Label>
            </div>
            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={() => setFilters(DEFAULT_FILTERS)}>
                Reset filters
              </Button>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label className="text-muted-foreground text-xs font-normal">Channels</Label>
            <div className="flex flex-wrap gap-3">
              {CHANNEL_OPTIONS.map((opt) => (
                <div key={opt.value} className="flex items-center gap-1.5">
                  <Checkbox
                    id={`graph-channel-${accountId}-${opt.value}`}
                    checked={filters.channels.includes(opt.value)}
                    onCheckedChange={(checked) => toggleListValue("channels", opt.value, !!checked)}
                  />
                  <Label
                    htmlFor={`graph-channel-${accountId}-${opt.value}`}
                    className="text-sm font-normal"
                  >
                    {opt.label}
                  </Label>
                </div>
              ))}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label className="text-muted-foreground text-xs font-normal">Roles</Label>
            <div className="flex flex-wrap gap-3">
              {GRAPH_ROLE_OPTIONS.map((opt) => (
                <div key={opt.value} className="flex items-center gap-1.5">
                  <Checkbox
                    id={`graph-role-${accountId}-${opt.value}`}
                    checked={filters.roles.includes(opt.value)}
                    onCheckedChange={(checked) => toggleListValue("roles", opt.value, !!checked)}
                  />
                  <Label htmlFor={`graph-role-${accountId}-${opt.value}`} className="text-sm font-normal">
                    {opt.label}
                  </Label>
                </div>
              ))}
            </div>
          </div>
        </div>

        {data && (
          <>
            <CytoscapeComponent
              elements={elements}
              stylesheet={stylesheet}
              style={{ width: "100%", height: "440px" }}
              cy={handleCyInit}
              wheelSensitivity={0.2}
            />

            <GraphLegend theme={theme} />

            {selectedNode && (
              <div className="rounded-lg border p-3 text-sm">
                <p className="mb-1 font-medium">{selectedNode.account_id}</p>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
                  <NodeDetailField label="Role" value={roleLabel(selectedNode.role)} />
                  <NodeDetailField
                    label="Role confidence"
                    value={`${(selectedNode.role_confidence * 100).toFixed(0)}%`}
                  />
                  <NodeDetailField label="Risk score" value={formatRiskScore(selectedNode.current_risk_score)} />
                  <NodeDetailField label="Hop distance" value={String(selectedNode.hop_distance ?? "—")} />
                  <NodeDetailField label="Branch city" value={selectedNode.branch_city ?? "—"} />
                  <NodeDetailField label="Prior SAR" value={selectedNode.has_prior_sar ? "Yes" : "No"} />
                </dl>
              </div>
            )}

            <p className="text-muted-foreground text-xs">
              {data.nodes.length} accounts · {data.edges.length} transactions at radius {data.radius}.
            </p>
          </>
        )}
      </div>
    </TriageSection>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <Label className="text-muted-foreground text-xs font-normal">{label}</Label>
      {children}
    </div>
  );
}

function NodeDetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

/** Secondary (non-color) encoding for role, per dataviz guidance — the
 * dark-mode role palette only clears the 6–8 CVD floor band, so color alone
 * isn't sufficient here. */
function GraphLegend({ theme }: { theme: GraphTheme }) {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs">
      {(["SOURCE", "MULE", "SINK", "NORMAL"] as const).map((role) => (
        <span key={role} className="flex items-center gap-1.5">
          <span
            className="inline-block size-3 rounded-full"
            style={{ backgroundColor: roleColor(theme, role) }}
          />
          {roleLabel(role)}
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block size-3 rounded-full border-2"
          style={{ backgroundColor: theme.centerFill, borderColor: theme.centerStroke }}
        />
        Account under investigation
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block size-3 rounded-full border-2 bg-transparent"
          style={{ borderColor: theme.statusFlag }}
        />
        Prior SAR
      </span>
      <span className="flex items-center gap-1.5">
        <Badge variant="outline" className="border-red-500/50 bg-red-500/10 text-red-700 dark:text-red-400">
          Dashed edge
        </Badge>
        Flagged as laundering
      </span>
    </div>
  );
}
