"use client";

import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { MoneyFlowNode, MoneyFlowResponse } from "@/lib/api/types";

// Non-interactive SVG only, per `docs/FRONTEND_ROADMAP.md` decision 3 — no
// cytoscape/force-graph for L1 (that's reserved for L2's full graph). Caps
// to the top `MAX_NODES_PER_SIDE` by amount per side so the diagram stays
// legible on a busy account; the rest are summarized as a text line below.
const MAX_NODES_PER_SIDE = 6;
const ROW_HEIGHT = 34;
const TOP_PADDING = 24;

/**
 * L1 Triage §4 — Simplified Money Flow. Also the source of the "most
 * frequent destination" stat (highest `pct_of_total` beneficiary) — shown
 * here rather than duplicated into the Transaction Summary card, since this
 * is the endpoint that already computes it (`FRONTEND_PLAN.md` §3.3 row 4).
 */
export function MoneyFlowSection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const { data, loading, error } = useTriageFetch<MoneyFlowResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/money-flow`,
  );

  const isEmpty = !!data && data.sources.length === 0 && data.beneficiaries.length === 0;

  return (
    <TriageSection
      title="Simplified Money Flow"
      description="One-hop inflow/outflow around the primary account."
      loading={loading}
      error={error}
      isEmpty={isEmpty}
      emptyText="No transaction flow recorded for this account."
    >
      {data && <MoneyFlowDiagram data={data} />}
    </TriageSection>
  );
}

function MoneyFlowDiagram({ data }: { data: MoneyFlowResponse }) {
  const sources = [...data.sources].sort((a, b) => b.total_amount - a.total_amount);
  const beneficiaries = [...data.beneficiaries].sort((a, b) => b.total_amount - a.total_amount);
  const shownSources = sources.slice(0, MAX_NODES_PER_SIDE);
  const shownBeneficiaries = beneficiaries.slice(0, MAX_NODES_PER_SIDE);
  const rows = Math.max(shownSources.length, shownBeneficiaries.length, 1);
  const height = rows * ROW_HEIGHT + TOP_PADDING * 2;
  const width = 640;
  const centerX = width / 2;
  const leftX = 120;
  const rightX = width - 120;

  const topDestination = [...data.beneficiaries].sort((a, b) => b.pct_of_total - a.pct_of_total)[0];

  return (
    <div className="flex flex-col gap-3">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Simplified money flow diagram"
        className="w-full"
      >
        <defs>
          <marker id="mf-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" className="fill-muted-foreground" />
          </marker>
        </defs>

        {/* Center node */}
        <g transform={`translate(${centerX}, ${height / 2})`}>
          <rect x={-60} y={-16} width={120} height={32} rx={6} className="fill-primary/10 stroke-primary" />
          <text textAnchor="middle" dy={4} className="fill-foreground text-[11px] font-medium">
            {truncateLabel(data.center, 16)}
          </text>
        </g>

        {shownSources.map((node, i) => {
          const y = TOP_PADDING + i * ROW_HEIGHT + ROW_HEIGHT / 2;
          return (
            <MoneyFlowEdge
              key={`src-${node.account_id}`}
              node={node}
              x={leftX}
              y={y}
              targetX={centerX - 62}
              targetY={height / 2}
              align="left"
            />
          );
        })}

        {shownBeneficiaries.map((node, i) => {
          const y = TOP_PADDING + i * ROW_HEIGHT + ROW_HEIGHT / 2;
          return (
            <MoneyFlowEdge
              key={`ben-${node.account_id}`}
              node={node}
              x={rightX}
              y={y}
              targetX={centerX + 62}
              targetY={height / 2}
              align="right"
            />
          );
        })}
      </svg>

      <div className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-muted-foreground sm:grid-cols-2">
        <p>
          Sources: {sources.length}
          {sources.length > MAX_NODES_PER_SIDE ? ` (top ${MAX_NODES_PER_SIDE} shown)` : ""}
        </p>
        <p>
          Beneficiaries: {beneficiaries.length}
          {beneficiaries.length > MAX_NODES_PER_SIDE ? ` (top ${MAX_NODES_PER_SIDE} shown)` : ""}
        </p>
      </div>

      {topDestination && (
        <p className="text-sm">
          <span className="text-muted-foreground">Most frequent destination: </span>
          <span className="font-medium">{topDestination.account_id}</span> —{" "}
          {topDestination.pct_of_total.toFixed(1)}% of outflow
        </p>
      )}
    </div>
  );
}

function MoneyFlowEdge({
  node,
  x,
  y,
  targetX,
  targetY,
  align,
}: {
  node: MoneyFlowNode;
  x: number;
  y: number;
  targetX: number;
  targetY: number;
  align: "left" | "right";
}) {
  const isSource = align === "left";
  const [x1, y1, x2, y2] = isSource ? [x + 55, y, targetX, targetY] : [targetX, targetY, x - 55, y];

  return (
    <g>
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        className="stroke-muted-foreground/50"
        strokeWidth={1.5}
        markerEnd="url(#mf-arrow)"
      />
      <rect
        x={x - 55}
        y={y - 14}
        width={110}
        height={28}
        rx={5}
        className="fill-card stroke-border"
      />
      <text textAnchor="middle" x={x} y={y - 2} className="fill-foreground text-[10px] font-medium">
        {truncateLabel(node.account_id, 14)}
      </text>
      <text textAnchor="middle" x={x} y={y + 10} className="fill-muted-foreground text-[9px]">
        {node.pct_of_total.toFixed(0)}% · {node.txn_count} txn
      </text>
    </g>
  );
}

function truncateLabel(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}
