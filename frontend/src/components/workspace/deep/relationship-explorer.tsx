"use client";

import type { Core, ElementDefinition, StylesheetJsonBlock } from "cytoscape";
import { useCallback, useMemo, useRef, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import "@/components/workspace/deep/graph-theme.css";
import { readGraphTheme, type GraphTheme } from "@/components/workspace/deep/graph-theme";
import { formatDateTime } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { RelationshipGraphResponse, RelationshipNode } from "@/lib/api/types";

// `investigation/relationship_discovery.py`'s documented confidence scheme
// (module docstring table) — plain-language labels for the exact 4
// `shared_attribute` values that module's discovery pass writes
// (`"pan" | "name" | "income_bracket" | "branch"` — note this is a
// narrower set than `demo_data/relationships.py`'s 7 seeded shared-value
// clusters; `phone`/`email`/`address`/`employer` clusters exist in demo
// data but are NOT matched by the discovery job, so those values never
// actually appear here). The numeric confidence itself is rendered
// directly per-edge (never collapsed into this label alone).
const SHARED_ATTRIBUTE_LABELS: Record<string, string> = {
  pan: "Shared PAN",
  name: "Similar name",
  income_bracket: "Shared income bracket",
  branch: "Shared branch city",
};

function sharedAttributeLabel(attribute: string): string {
  return SHARED_ATTRIBUTE_LABELS[attribute] ?? attribute;
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function buildElements(
  data: RelationshipGraphResponse,
  selectedId: string | null,
): ElementDefinition[] {
  const nodes: ElementDefinition[] = data.nodes.map((n) => ({
    data: {
      id: n.customer_id,
      label: truncate(n.name || n.customer_id, 14),
      inCaseScope: n.in_case_scope,
      isSelected: n.customer_id === selectedId,
    },
  }));

  const edges: ElementDefinition[] = data.edges.map((e) => ({
    data: {
      id: `rel-${e.id}`,
      source: e.entity_a,
      target: e.entity_b,
      // The confidence number IS the finding (ROADMAP Phase 18) — shown
      // directly as the edge's own label, not collapsed into a boolean
      // "related" flag or hidden behind a click.
      label: `${sharedAttributeLabel(e.shared_attribute)} · ${e.confidence.toFixed(2)}`,
      confidence: e.confidence,
      isSelected: `rel-${e.id}` === selectedId,
    },
  }));

  return [...nodes, ...edges];
}

function buildStylesheet(theme: GraphTheme): StylesheetJsonBlock[] {
  const rules: Array<{ selector: string; style: Record<string, unknown> }> = [
    {
      selector: "node",
      style: {
        shape: "ellipse",
        "background-color": theme.relInScope,
        width: 40,
        height: 40,
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
      // Falsy-boolean selector (`[!field]` — cytoscape's own boolean-data
      // grammar, matching this file's neighbor `investigation-graph.tsx`'s
      // `[?field]` truthy usage) — an out-of-case-scope customer gets both
      // a distinct shape (diamond, the real secondary/CVD-safe channel)
      // and a distinct color, never color alone, per dataviz guidance.
      selector: "node[!inCaseScope]",
      style: {
        shape: "diamond",
        "background-color": theme.relOutOfScope,
        width: 46,
        height: 46,
        "border-width": 3,
        "border-color": theme.relOutOfScope,
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
        // Linear (not log) width mapping — `confidence` is already a
        // bounded 0..1 ratio, not a magnitude spanning orders of
        // magnitude the way transaction amounts do (contrast
        // `investigation-graph.tsx`'s log-scale edge width).
        width: "mapData(confidence, 0, 1, 1.5, 7)",
        "line-color": theme.relEdge,
        "target-arrow-shape": "none",
        "curve-style": "bezier",
        label: "data(label)",
        "font-size": 7,
        color: theme.label,
        opacity: 0.9,
        "overlay-opacity": 0,
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

function nodeName(nodes: RelationshipNode[], customerId: string): string {
  return nodes.find((n) => n.customer_id === customerId)?.name || customerId;
}

/**
 * L2 §2 — Relationship Explorer, `GET .../relationships` (ROADMAP
 * Phase 18). Nodes are CUSTOMERS (not accounts, unlike
 * `investigation-graph.tsx`) and edges are shared-attribute matches, not
 * transactions — a structurally different graph, so this is a fresh
 * `cytoscape` consumer rather than a variant of that component, though it
 * follows the exact same conventions (theme via `graph-theme.ts`/`.css`,
 * `buildElements`/`buildStylesheet`, `handleCyInit` with a
 * `cyInstanceRef` guard, legend).
 *
 * The single most important thing this view can surface: a customer with
 * `in_case_scope: false` — no direct transaction link to this case, only
 * a shared PAN/name/income-bracket/branch match with someone who IS in
 * scope (`SYSTEM_DEVELOPMENT_PLAN.md` §4.2's "no one else does this"
 * feature). That state gets its own shape+color encoding on the graph
 * AND an explicit callout banner above it — deliberately not something an
 * investigator could miss by not noticing one diamond among many circles.
 */
export function RelationshipExplorerSection({ caseId }: { caseId: string }) {
  const { data, loading, error } = useTriageFetch<RelationshipGraphResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/relationships`,
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const theme = useMemo(() => readGraphTheme(), []);
  const elements = useMemo(
    () => (data ? buildElements(data, selectedId) : []),
    [data, selectedId],
  );
  const stylesheet = useMemo(() => buildStylesheet(theme), [theme]);

  const cyInstanceRef = useRef<Core | null>(null);
  const handleCyInit = useCallback((cy: Core) => {
    if (cyInstanceRef.current === cy) return;
    cyInstanceRef.current = cy;
    cy.on("tap", "node, edge", (evt) => setSelectedId(evt.target.id()));
    cy.on("tap", (evt) => {
      if (evt.target === cy) setSelectedId(null);
    });
    cy.layout({ name: "cose", animate: false, fit: true, padding: 30 }).run();
  }, []);

  const outOfScopeNodes = (data?.nodes ?? []).filter((n) => !n.in_case_scope);
  const selectedNode = data?.nodes.find((n) => n.customer_id === selectedId) ?? null;
  const selectedEdge = data?.edges.find((e) => `rel-${e.id}` === selectedId) ?? null;

  return (
    <TriageSection
      title="Relationship Explorer"
      description="Customers linked to this case's own customers via a shared attribute (PAN, name, income bracket, or branch city) — not necessarily a direct transaction. Confidence is shown per relationship, not collapsed into a yes/no."
      loading={loading}
      error={error}
      isEmpty={!!data && data.nodes.length === 0}
      emptyText="No discovered relationships touch this case's customers."
    >
      <div className="flex flex-col gap-4">
        {outOfScopeNodes.length > 0 && (
          <Alert className="border-orange-500/50 bg-orange-500/5">
            <AlertTitle className="text-orange-700 dark:text-orange-400">
              {outOfScopeNodes.length} customer{outOfScopeNodes.length === 1 ? "" : "s"} outside this
              case&apos;s normal scope
            </AlertTitle>
            <AlertDescription>
              {outOfScopeNodes.map((n) => n.name || n.customer_id).join(", ")} share
              {outOfScopeNodes.length === 1 ? "s" : ""} an attribute with a customer on this case but{" "}
              {outOfScopeNodes.length === 1 ? "has" : "have"} no direct transaction link to it —
              shown as the diamond-shaped node{outOfScopeNodes.length === 1 ? "" : "s"} below.
            </AlertDescription>
          </Alert>
        )}

        {data && (
          <>
            <CytoscapeComponent
              elements={elements}
              stylesheet={stylesheet}
              style={{ width: "100%", height: "400px" }}
              cy={handleCyInit}
              wheelSensitivity={0.2}
            />

            <RelationshipLegend theme={theme} />

            {(selectedNode || selectedEdge) && (
              <div className="rounded-lg border p-3 text-sm">
                {selectedNode && (
                  <>
                    <p className="mb-1 font-medium">{selectedNode.name || selectedNode.customer_id}</p>
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
                      <DetailField label="Customer ID" value={selectedNode.customer_id} />
                      <DetailField label="Name" value={selectedNode.name ?? "—"} />
                      <DetailField
                        label="Case scope"
                        value={selectedNode.in_case_scope ? "In this case" : "Outside this case"}
                      />
                    </dl>
                    {!selectedNode.in_case_scope && (
                      <p className="text-muted-foreground mt-2 text-xs">
                        This customer has no direct transaction link to this case — surfaced only via
                        a shared-attribute match with a customer who is in scope.
                      </p>
                    )}
                  </>
                )}
                {selectedEdge && data && (
                  <>
                    <p className="mb-1 font-medium">
                      {nodeName(data.nodes, selectedEdge.entity_a)} ↔{" "}
                      {nodeName(data.nodes, selectedEdge.entity_b)}
                    </p>
                    <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
                      <DetailField
                        label="Shared attribute"
                        value={sharedAttributeLabel(selectedEdge.shared_attribute)}
                      />
                      <DetailField label="Confidence" value={selectedEdge.confidence.toFixed(2)} />
                      <DetailField label="Method" value={selectedEdge.method} />
                      <DetailField label="Discovered" value={formatDateTime(selectedEdge.discovered_at)} />
                    </dl>
                  </>
                )}
              </div>
            )}

            <p className="text-muted-foreground text-xs">
              {data.nodes.length} customer{data.nodes.length === 1 ? "" : "s"} ·{" "}
              {data.edges.length} relationship{data.edges.length === 1 ? "" : "s"}.
            </p>
          </>
        )}
      </div>
    </TriageSection>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}

function RelationshipLegend({ theme }: { theme: GraphTheme }) {
  return (
    <div className="flex flex-wrap items-center gap-4 text-xs">
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block size-3 rounded-full"
          style={{ backgroundColor: theme.relInScope }}
        />
        In this case
      </span>
      <span className="flex items-center gap-1.5">
        <span
          className="inline-block size-3 rotate-45"
          style={{ backgroundColor: theme.relOutOfScope }}
        />
        Outside this case (shared-attribute match only)
      </span>
      <span className="flex items-center gap-1.5">
        <Badge variant="outline">attribute · confidence</Badge>
        Edge label — the match confidence, shown per relationship, never collapsed to yes/no.
      </span>
    </div>
  );
}
