"use client";

import cytoscape from "cytoscape";
import dagre from "cytoscape-dagre";
import type { Core, ElementDefinition, LayoutOptions, StylesheetJsonBlock } from "cytoscape";
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
import { readGraphTheme, roleColor, roleLabel, truncate, type GraphTheme } from "@/components/workspace/deep/graph-theme";
import { formatRiskScore } from "@/components/dashboard/format";
import { CHANNEL_OPTIONS, GRAPH_ROLE_OPTIONS } from "@/lib/workspace/channel-options";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { FilterField, TriageSection } from "@/components/workspace/triage/triage-section";
import type { NHopGraphResponse } from "@/lib/api/types";

// Registers the `dagre` layout extension with cytoscape exactly once.
// `cytoscape.use(...)` throws if the same extension is registered twice —
// Next.js Fast Refresh re-runs this module's top-level code on every hot
// reload of this file (or anything that imports it) in dev, so a bare
// unconditional `cytoscape.use(dagre)` would throw on the second edit even
// though nothing is actually broken. Guarded by a `globalThis` flag (not a
// module-scope `let`, which Fast Refresh can reset along with the rest of
// the module) plus a `try/catch` as a second line of defense.
const dagreRegistryFlag = globalThis as typeof globalThis & { __cytoscapeDagreRegistered?: boolean };
if (!dagreRegistryFlag.__cytoscapeDagreRegistered) {
  try {
    cytoscape.use(dagre);
  } catch {
    // Already registered elsewhere in this same module instance — safe to
    // ignore.
  }
  dagreRegistryFlag.__cytoscapeDagreRegistered = true;
}

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

/**
 * `filters.end` is a bare `YYYY-MM-DD` string from a `type="date"` input;
 * the backend parses `end` as an exact `datetime` compared with `<=`, so
 * passing it through as-is lands on that date's midnight and silently
 * excludes almost the entire selected end day — same fix as
 * `alert-query.ts::endOfDayParam` / `transaction-summary.tsx`'s identical
 * local convention, applied here too.
 */
function endOfDayParam(dateOnly: string): string {
  return `${dateOnly}T23:59:59.999`;
}

function buildGraphUrl(caseId: string, accountId: string, filters: GraphFilterState): string {
  const qs = new URLSearchParams();
  qs.set("radius", String(filters.radius));
  if (filters.suspiciousOnly) qs.set("suspicious_only", "true");
  if (filters.minRiskScore) qs.set("min_risk_score", filters.minRiskScore);
  if (filters.minAmount) qs.set("min_amount", filters.minAmount);
  if (filters.maxAmount) qs.set("max_amount", filters.maxAmount);
  if (filters.start) qs.set("start", filters.start);
  if (filters.end) qs.set("end", endOfDayParam(filters.end));
  for (const c of filters.channels) qs.append("channels", c);
  if (filters.direction) qs.set("direction", filters.direction);
  for (const r of filters.roles) qs.append("roles", r);
  if (filters.priorSarOnly) qs.set("prior_sar_only", "true");
  return `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/graph?${qs.toString()}`;
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
 * filter set wired to `GET .../graph`, laid out with `cytoscape-dagre`
 * (`rankDir: "LR"`) so money flow reads left-to-right (senders left,
 * receivers right) — the standard hierarchical/layered-digraph layout for
 * that requirement on an arbitrary multi-hop directed graph (unlike the
 * single-hop `triage/money-flow.tsx`/`deep/graph-replay.tsx`, a strict
 * "every sender left of every receiver" total order isn't always possible
 * here, e.g. across a cycle — dagre ranks by traversal depth instead).
 * Previously a `concentric` ring layout keyed on `hop_distance`, which kept
 * the hop structure legible but didn't encode flow direction spatially at
 * all.
 *
 * `selectedTxnId`/`onSelectTxn` are lifted to `deep-view.tsx` so a timeline
 * click highlights the matching edge here (and, the other direction,
 * clicking an edge here highlights its timeline row) — pure client-side
 * `txn_id` matching, per the designed data contract, no extra fetch.
 * `selectedAccountId`/`onSelectAccount` (ROADMAP Phase 18) are lifted the
 * same way, so the Evidence Management section can offer a "bookmark the
 * account currently selected in the graph" quick action without this
 * component needing to know anything about evidence.
 */
export function InvestigationGraphSection({
  caseId,
  accountId,
  selectedTxnId,
  onSelectTxn,
  selectedAccountId,
  onSelectAccount,
}: {
  caseId: string;
  accountId: string;
  selectedTxnId: string | null;
  onSelectTxn: (txnId: string | null) => void;
  selectedAccountId: string | null;
  onSelectAccount: (accountId: string | null) => void;
}) {
  const [filters, setFilters] = useState<GraphFilterState>(DEFAULT_FILTERS);

  const url = useMemo(() => buildGraphUrl(caseId, accountId, filters), [caseId, accountId, filters]);
  const { data, loading, error } = useTriageFetch<NHopGraphResponse>(url);

  const theme = useMemo(() => readGraphTheme(), []);
  const elements = useMemo(
    () => (data ? buildElements(data, theme, selectedTxnId, selectedAccountId) : []),
    [data, theme, selectedTxnId, selectedAccountId],
  );
  const stylesheet = useMemo(() => buildStylesheet(theme), [theme]);
  const selectedNode = useMemo(
    () => data?.nodes.find((n) => n.account_id === selectedAccountId) ?? null,
    [data, selectedAccountId],
  );

  // `dagre`'s `rankDir: "LR"` stacks same-rank nodes along the Y axis, and
  // `fit: true` (below) uniformly scales the ENTIRE computed layout — both
  // axes — to fit whatever container box it's given. A fixed-height
  // container was fine for the previous `concentric` layout (rings spread
  // radially, using both axes), but under `rankDir: "LR"` a busy hub
  // account with many same-hop siblings all lands in one rank, and `fit`
  // silently compresses that rank's `nodeSep` spacing down to fit a fixed
  // box — exactly the "nodes stacked/overlapping" report, not a dagre
  // misconfiguration. Sizing the container's height to the graph's actual
  // widest rank (approximated by the largest `hop_distance` bucket — not
  // dagre's literal internal rank assignment, but a close enough proxy
  // without re-deriving dagre's own ranking) keeps `fit`'s compression
  // factor close to 1 for busy graphs instead of forcing every graph into
  // the same 700px box regardless of how wide it actually is. The
  // already-scrollable ancestor (`case-tab-content.tsx`'s `max-h-[75vh]
  // overflow-y-auto`) absorbs any resulting height beyond the viewport —
  // no separate inner scroll region needed.
  const graphHeight = useMemo(() => {
    if (!data || data.nodes.length === 0) return 700;
    const countsByHop = new Map<number, number>();
    for (const n of data.nodes) {
      const hop = n.hop_distance ?? 0;
      countsByHop.set(hop, (countsByHop.get(hop) ?? 0) + 1);
    }
    const maxPerRank = Math.max(1, ...countsByHop.values());
    // ~130px/node: node diameter (up to 64px, `mapData(risk, 0, 100, 22,
    // 64)`) + `nodeSep` (70) + label headroom, rounded up for breathing
    // room. Live-measured against a real case: a hub account's radius-3
    // ego-graph put 68 nodes in one rank — a real, not hypothetical, case
    // this needs to handle. Deliberately NOT capped tightly: the ancestor
    // (`case-tab-content.tsx`'s `max-h-[75vh] overflow-y-auto`) already
    // scrolls, so a tall canvas is normal, expected scrolling, not broken
    // layout — and re-compressing a busy rank back down would reintroduce
    // the exact overlap this height calculation exists to prevent. The
    // 6000px ceiling is a sanity bound against a truly degenerate rank
    // (hundreds of nodes), not a routine limit; the existing zoom-out
    // control is the deliberate way to get an overview beyond that.
    return Math.min(6000, Math.max(700, maxPerRank * 130));
  }, [data]);

  const cyInstanceRef = useRef<Core | null>(null);
  const onSelectTxnRef = useRef(onSelectTxn);
  const onSelectAccountRef = useRef(onSelectAccount);

  useEffect(() => {
    onSelectTxnRef.current = onSelectTxn;
  }, [onSelectTxn]);

  useEffect(() => {
    onSelectAccountRef.current = onSelectAccount;
  }, [onSelectAccount]);

  // Re-run the layout only when a fresh graph arrives (new `data`), not on
  // every selection change — `cy={...}`'s callback fires on every cytoscape
  // update, so `cyInstanceRef` guards against re-attaching click listeners
  // more than once for the same instance.
  const handleCyInit = useCallback((cy: Core) => {
    if (cyInstanceRef.current === cy) return;
    cyInstanceRef.current = cy;
    cy.on("tap", "node", (evt) => {
      onSelectAccountRef.current(evt.target.id());
    });
    cy.on("tap", "edge", (evt) => {
      const txnId = evt.target.id();
      onSelectTxnRef.current(txnId);
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) onSelectAccountRef.current(null);
    });
  }, []);

  // `dagre`, `rankDir: "LR"` — a real hierarchical/layered directed-graph
  // layout, not a ring layout. This graph is a genuine multi-hop directed
  // graph (arbitrary `source_account`/`dest_account` edges, possibly with
  // cycles), so a strict "every sender strictly left of every receiver"
  // rule is graph-theoretically impossible in general (a cycle A->B->C->A
  // can't be totally ordered left-to-right) — `dagre` is the standard tool
  // for "make flow direction read left-to-right" on exactly this shape of
  // graph: it ranks nodes by traversal depth along edge direction, breaking
  // cycles internally, so the graph reads left-to-right in aggregate flow
  // direction even where a literal total order doesn't exist. Reads the
  // same `source`/`target` fields already on every edge element
  // (`buildElements`'s `source: e.source_account, target: e.dest_account`)
  // — no data-shape change needed, this is purely a layout-algorithm swap
  // from the previous `concentric` (ring) layout.
  //
  // `nodeSep`/`rankSep` bumped well past dagre's defaults (50/50) for the
  // same "illegible clump" reason the previous `concentric` layout's
  // `minNodeSpacing` was bumped — a busy multi-hop graph needs generous
  // breathing room to stay legible at this canvas size.
  useEffect(() => {
    const cy = cyInstanceRef.current;
    if (!cy || !data) return;
    cy.layout({
      name: "dagre",
      rankDir: "LR",
      nodeSep: 70,
      rankSep: 120,
      fit: true,
      animate: false,
    } as unknown as LayoutOptions).run();
  }, [data]);

  function zoomBy(factor: number) {
    const cy = cyInstanceRef.current;
    if (!cy) return;
    cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }

  function resetView() {
    cyInstanceRef.current?.fit(undefined, 30);
  }

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
                  aria-label="Radius, in hops"
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
                aria-label="Minimum risk score"
              />
            </div>

            <FilterField label="Min amount">
              <Input
                type="number"
                inputMode="decimal"
                aria-label="Min amount"
                className="w-28"
                value={filters.minAmount}
                onChange={(e) => updateFilter("minAmount", e.target.value)}
              />
            </FilterField>
            <FilterField label="Max amount">
              <Input
                type="number"
                inputMode="decimal"
                aria-label="Max amount"
                className="w-28"
                value={filters.maxAmount}
                onChange={(e) => updateFilter("maxAmount", e.target.value)}
              />
            </FilterField>
            <FilterField label="From">
              <Input
                type="date"
                aria-label="From date"
                className="w-36"
                value={filters.start}
                onChange={(e) => updateFilter("start", e.target.value)}
              />
            </FilterField>
            <FilterField label="To">
              <Input
                type="date"
                aria-label="To date"
                className="w-36"
                value={filters.end}
                onChange={(e) => updateFilter("end", e.target.value)}
              />
            </FilterField>
            <FilterField label="Direction">
              <Select
                value={filters.direction || ALL}
                onValueChange={(value) =>
                  updateFilter("direction", value === ALL ? "" : (String(value) as "in" | "out"))
                }
              >
                <SelectTrigger size="sm" className="w-28" aria-label="Direction">
                  <SelectValue>
                    {(value: string) => (value === ALL ? "Any" : value === "in" ? "Inbound" : "Outbound")}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>Any</SelectItem>
                  <SelectItem value="in">Inbound</SelectItem>
                  <SelectItem value="out">Outbound</SelectItem>
                </SelectContent>
              </Select>
            </FilterField>
          </div>

          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-1.5">
              <Checkbox
                id={`graph-suspicious-${caseId}-${accountId}`}
                checked={filters.suspiciousOnly}
                onCheckedChange={(checked) => updateFilter("suspiciousOnly", !!checked)}
              />
              <Label htmlFor={`graph-suspicious-${caseId}-${accountId}`} className="text-sm font-normal">
                Suspicious transactions only
              </Label>
            </div>
            <div className="flex items-center gap-1.5">
              <Checkbox
                id={`graph-prior-sar-${caseId}-${accountId}`}
                checked={filters.priorSarOnly}
                onCheckedChange={(checked) => updateFilter("priorSarOnly", !!checked)}
              />
              <Label htmlFor={`graph-prior-sar-${caseId}-${accountId}`} className="text-sm font-normal">
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
                    id={`graph-channel-${caseId}-${accountId}-${opt.value}`}
                    checked={filters.channels.includes(opt.value)}
                    onCheckedChange={(checked) => toggleListValue("channels", opt.value, !!checked)}
                  />
                  <Label
                    htmlFor={`graph-channel-${caseId}-${accountId}-${opt.value}`}
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
                    id={`graph-role-${caseId}-${accountId}-${opt.value}`}
                    checked={filters.roles.includes(opt.value)}
                    onCheckedChange={(checked) => toggleListValue("roles", opt.value, !!checked)}
                  />
                  <Label htmlFor={`graph-role-${caseId}-${accountId}-${opt.value}`} className="text-sm font-normal">
                    {opt.label}
                  </Label>
                </div>
              ))}
            </div>
          </div>
        </div>

        {data && (
          <>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="icon-sm" onClick={() => zoomBy(1.2)} title="Zoom in">
                +
              </Button>
              <Button variant="outline" size="icon-sm" onClick={() => zoomBy(1 / 1.2)} title="Zoom out">
                −
              </Button>
              <Button variant="outline" size="sm" onClick={resetView}>
                Reset view
              </Button>
            </div>

            <CytoscapeComponent
              elements={elements}
              stylesheet={stylesheet}
              // `graphHeight` (see its own comment above) scales with the
              // graph's busiest rank so `fit: true` below doesn't compress
              // same-rank node spacing into overlap for a busy hub account.
              style={{ width: "100%", height: `${graphHeight}px` }}
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
