"use client";

import React, { useEffect, useRef, useCallback } from "react";
import cytoscape, { Core, ElementDefinition } from "cytoscape";
import { GraphData } from "@/lib/api";

const RISK_COLORS: Record<string, string> = {
  CRITICAL: "#ef4444",
  HIGH:     "#f97316",
  MEDIUM:   "#eab308",
  LOW:      "#22c55e",
};

const RISK_FILL: Record<string, string> = {
  CRITICAL: "rgba(239,68,68,0.15)",
  HIGH:     "rgba(249,115,22,0.15)",
  MEDIUM:   "rgba(234,179,8,0.15)",
  LOW:      "rgba(34,197,94,0.15)",
};

const NODE_SIZES: Record<string, number> = {
  CRITICAL: 48,
  HIGH:     40,
  MEDIUM:   34,
  LOW:      28,
};

const ROLE_SHAPES: Record<string, string> = {
  MULE:       "diamond",
  COLLECTOR:  "star",
  SMURFER:    "pentagon",
  TRANSIENT:  "ellipse",
  SOURCE:     "triangle",
  SINK:       "vee",
  NORMAL:     "ellipse",
};

interface CytoscapeGraphProps {
  data: GraphData | null;
  onNodeClick?: (nodeId: string) => void;
  className?: string;
  layoutHint?: "cose" | "circle" | "breadthfirst" | "concentric";
  egoMode?: boolean;
  centerId?: string;
}

export default function CytoscapeGraph({
  data,
  onNodeClick,
  className = "",
  layoutHint,
  egoMode,
  centerId,
}: CytoscapeGraphProps) {
  const containerRef    = useRef<HTMLDivElement>(null);
  const cyRef           = useRef<Core | null>(null);
  const pulseIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // BFS from centerId to compute hop levels (0=center, 1=1st-hop, 2=2nd-hop)
  const computeHopLevels = useCallback(
    (graphData: GraphData, center: string): Map<string, number> => {
      const levels = new Map<string, number>();
      levels.set(center, 0);
      const adj = new Map<string, string[]>();
      for (const e of graphData.edges) {
        if (!adj.has(e.source)) adj.set(e.source, []);
        if (!adj.has(e.target)) adj.set(e.target, []);
        adj.get(e.source)!.push(e.target);
        adj.get(e.target)!.push(e.source);
      }
      const queue = [center];
      while (queue.length) {
        const curr   = queue.shift()!;
        const lvl    = levels.get(curr)!;
        if (lvl >= 2) continue;
        for (const nb of adj.get(curr) || []) {
          if (!levels.has(nb)) {
            levels.set(nb, lvl + 1);
            queue.push(nb);
          }
        }
      }
      return levels;
    },
    []
  );

  // Union-Find to detect the connected component with highest avg risk_score
  const findSuspiciousSubgraph = useCallback(
    (graphData: GraphData): Set<string> => {
      const parent = new Map<string, string>();
      const find   = (x: string): string => {
        if (parent.get(x) !== x) parent.set(x, find(parent.get(x)!));
        return parent.get(x)!;
      };
      const union = (a: string, b: string) => parent.set(find(a), find(b));

      for (const n of graphData.nodes) parent.set(n.id, n.id);
      for (const e of graphData.edges) {
        if (parent.has(e.source) && parent.has(e.target))
          union(e.source, e.target);
      }

      const components = new Map<string, string[]>();
      for (const n of graphData.nodes) {
        const root = find(n.id);
        if (!components.has(root)) components.set(root, []);
        components.get(root)!.push(n.id);
      }

      const nodeRisk = new Map(graphData.nodes.map((n) => [n.id, n.risk_score]));
      let bestRoot   = "";
      let bestScore  = -1;
      for (const [root, members] of components) {
        if (members.length < 2) continue;
        const avg =
          members.reduce((s, id) => s + (nodeRisk.get(id) || 0), 0) /
          members.length;
        if (avg > bestScore) { bestScore = avg; bestRoot = root; }
      }
      if (!bestRoot) return new Set();
      return new Set(components.get(bestRoot) || []);
    },
    []
  );

  const buildElements = useCallback(
    (graphData: GraphData): ElementDefinition[] => {
      const elements: ElementDefinition[] = [];
      if (!graphData?.nodes) return elements;

      const nodeIds       = new Set<string>();
      const criticalIds   = new Set<string>();
      const hopLevels     =
        egoMode && centerId ? computeHopLevels(graphData, centerId) : null;

      // ── Nodes ────────────────────────────────────────────────────────────
      for (const node of graphData.nodes) {
        if (!node?.id) continue;
        nodeIds.add(node.id);
        const rl = node.risk_level || "LOW";
        if (rl === "CRITICAL") criticalIds.add(node.id);
        const hopLevel = hopLevels?.get(node.id) ?? -1;
        elements.push({
          data: {
            id:         node.id,
            label:      node.id.replace(/^ACC_/, ""),
            risk_score: node.risk_score ?? 0,
            risk_level: rl,
            risk_color: RISK_COLORS[rl] || "#6b7280",
            risk_fill:  RISK_FILL[rl]   || "rgba(107,114,128,0.15)",
            role:       node.role || "NORMAL",
            is_center:  node.is_center || false,
            hop_level:  hopLevel,
            node_size:  NODE_SIZES[rl] || 28,
          },
        });
      }

      // ── Edges ────────────────────────────────────────────────────────────
      const edges      = graphData.edges || [];
      const validEdges = edges.filter(
        (e) => e && nodeIds.has(e.source) && nodeIds.has(e.target)
      );
      // Cap at 150, prefer highest-amount edges
      const cappedEdges =
        validEdges.length > 150
          ? validEdges
              .sort((a, b) => (b.amount || 0) - (a.amount || 0))
              .slice(0, 150)
          : validEdges;

      for (let i = 0; i < cappedEdges.length; i++) {
        const edge = cappedEdges[i];
        const amt  = edge.amount || 0;
        // log-scale width: 1–4 px
        const logW =
          amt > 0 ? Math.min(4, Math.max(1, Math.log10(amt + 1) * 0.75)) : 1;
        const abbr =
          amt >= 1e7
            ? `₹${(amt / 1e7).toFixed(1)}Cr`
            : amt >= 1e5
            ? `₹${(amt / 1e5).toFixed(1)}L`
            : `₹${(amt / 1e3).toFixed(0)}K`;
        elements.push({
          data: {
            id:              `e${i}`,
            source:          edge.source,
            target:          edge.target,
            amount:          amt,
            channel:         edge.channel || "",
            label:           abbr,
            edge_width:      logW,
            is_critical_src: criticalIds.has(edge.source),
          },
        });
      }

      return elements;
    },
    [egoMode, centerId, computeHopLevels]
  );

  useEffect(() => {
    if (
      !containerRef.current ||
      !data ||
      !data.nodes ||
      data.nodes.length === 0
    )
      return;

    // Clear any existing pulse animation
    if (pulseIntervalRef.current) {
      clearInterval(pulseIntervalRef.current);
      pulseIntervalRef.current = null;
    }

    let elements: ElementDefinition[];
    try {
      elements = buildElements(data);
    } catch (e) {
      console.error("CytoscapeGraph: buildElements failed", e);
      return;
    }
    if (elements.length === 0) return;

    if (cyRef.current) {
      try { cyRef.current.destroy(); } catch { /* ignore */ }
      cyRef.current = null;
    }

    try {
      const cy = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          // ── Base node style ──────────────────────────────────────────────
          {
            selector: "node",
            style: {
              "background-color": "data(risk_fill)",
              "border-color":     "data(risk_color)",
              "border-width":     2,
              label:              "data(label)",
              "font-size":        "10px",
              color:              "#e2e8f0",
              "text-outline-color": "#0b1120",
              "text-outline-width": 2,
              "text-valign":      "bottom",
              "text-margin-y":    5,
              width:              "data(node_size)",
              height:             "data(node_size)",
              shape:              (ele: cytoscape.NodeSingular) =>
                (ROLE_SHAPES[ele.data("role")] || "ellipse") as cytoscape.Css.NodeShape,
              "overlay-opacity":  0,
            } as cytoscape.Css.Node,
          },
          // ── Ego: center node (hop 0) ─────────────────────────────────────
          {
            selector: "node[hop_level = 0]",
            style: {
              width:          60,
              height:         60,
              "border-width": 4,
              "border-color": "#3b82f6",
              "font-weight":  "bold",
              "font-size":    "12px",
            },
          },
          // ── Ego: 1st-hop neighbors ───────────────────────────────────────
          {
            selector: "node[hop_level = 1]",
            style: {
              "border-width": 2,
              "border-color": "#f97316",
            },
          },
          // ── Ego: 2nd-hop neighbors ───────────────────────────────────────
          {
            selector: "node[hop_level = 2]",
            style: {
              width:          24,
              height:         24,
              "border-width": 1,
              "border-color": "#64748b",
            },
          },
          // ── Graph Validation: center node — must be unmistakable no matter
          // its own risk level, so it gets a solid fill/color distinct from
          // the translucent risk-level palette used everywhere else, plus a
          // sharply larger size. Placed after the hop-level rules so it wins
          // when both match (Cytoscape uses last-matching-selector wins).
          {
            selector: "node[?is_center]",
            style: {
              "background-color": "#3b82f6",
              "background-opacity": 1,
              "border-color":     "#ffffff",
              "border-width":     5,
              width:              70,
              height:             70,
              "font-weight":      "bold",
              "font-size":        "13px",
              "z-index":          999,
            } as cytoscape.Css.Node,
          },
          // ── Selected ─────────────────────────────────────────────────────
          {
            selector: "node:selected",
            style: {
              "border-width": 4,
              "border-color": "#60a5fa",
            },
          },
          // ── Suspicious subgraph flash class ──────────────────────────────
          {
            selector: "node.suspicious",
            style: {
              "border-color": "#ef4444",
              "border-width": 4,
            },
          },
          // ── Base edge style ──────────────────────────────────────────────
          {
            selector: "edge",
            style: {
              width:                "data(edge_width)",
              "line-color":         "#64748b",
              "target-arrow-color": "#64748b",
              "target-arrow-shape": "triangle",
              "curve-style":        "bezier",
              opacity:              0.7,
              "font-size":          "8px",
              color:                "#94a3b8",
              "text-outline-color": "#0b1120",
              "text-outline-width": 1,
              label:                egoMode ? "data(label)" : "",
            } as cytoscape.Css.Edge,
          },
          // ── CRITICAL-source edges ────────────────────────────────────────
          {
            selector: "edge[?is_critical_src]",
            style: {
              "line-color":         "rgba(239,68,68,0.6)",
              "target-arrow-color": "rgba(239,68,68,0.6)",
            },
          },
          // ── Selected edge ────────────────────────────────────────────────
          {
            selector: "edge:selected",
            style: {
              "line-color":         "#60a5fa",
              "target-arrow-color": "#60a5fa",
              opacity:              1,
              label:                "data(label)",
            },
          },
        ],

        layout: (() => {
          if (egoMode) {
            return {
              name:          "cose",
              animate:       false,
              nodeRepulsion: () => 6000,
              idealEdgeLength: () => 100,
              gravity:       0.5,
              numIter:       50,
              randomize:     false,
            };
          }
          switch (layoutHint) {
            case "circle":
              return { name: "circle", animate: false, spacingFactor: 1.5 };
            case "breadthfirst":
              return { name: "breadthfirst", animate: false, directed: true, spacingFactor: 1.2 };
            case "concentric":
              return {
                name:       "concentric",
                animate:    false,
                concentric: (n: cytoscape.NodeSingular) => n.data("risk_score") || 0,
                levelWidth: () => 2,
              };
            default:
              return {
                name:            "cose",
                animate:         false,
                nodeRepulsion:   () => 4000,
                idealEdgeLength: () => 120,
                gravity:         0.4,
                numIter:         30,
                randomize:       false,
              };
          }
        })() as cytoscape.CoseLayoutOptions,

        wheelSensitivity: 0.3,
        minZoom:          0.2,
        maxZoom:          4,
      });

      // ── Event handlers ─────────────────────────────────────────────────
      cy.on("tap", "node", (evt) => {
        if (onNodeClick) onNodeClick(evt.target.id());
      });

      cy.on("mouseover", "node", (evt) => {
        const node = evt.target;
        node.style("border-color", "#ffffff");
        node.style("border-width", 3);
        if (containerRef.current) containerRef.current.style.cursor = "pointer";
      });

      cy.on("mouseout", "node", (evt) => {
        const node = evt.target;
        if (!node.selected()) node.removeStyle("border-color border-width");
        if (containerRef.current) containerRef.current.style.cursor = "default";
      });

      cy.on("mouseover", "edge", (evt) => {
        evt.target.style("label", evt.target.data("label"));
        evt.target.style("opacity", 1);
      });

      cy.on("mouseout", "edge", (evt) => {
        if (!evt.target.selected() && !egoMode) {
          evt.target.style("label", "");
          evt.target.style("opacity", 0.7);
        }
      });

      cyRef.current = cy;

      // ── Post-layout actions ────────────────────────────────────────────
      cy.one("layoutstop", () => {
        if (!cyRef.current || !containerRef.current) return;
        try { cy.fit(undefined, 30); } catch { /* ignore */ }

        // Ego mode: pulse center node border-width
        if (egoMode && centerId) {
          const centerNode = cy.getElementById(centerId);
          if (centerNode.length > 0) {
            let growing = false;
            pulseIntervalRef.current = setInterval(() => {
              try {
                if (!cyRef.current) return;
                growing = !growing;
                centerNode.animate({
                  style:    { "border-width": growing ? 8 : 4 } as cytoscape.Css.Node,
                  duration: 600,
                  easing:   "ease-in-out-sine",
                });
              } catch { /* ignore */ }
            }, 750);
          }
        }

        // Network mode: highlight the most suspicious connected component
        if (!egoMode && data.nodes.length > 3) {
          const suspiciousIds = findSuspiciousSubgraph(data);
          if (suspiciousIds.size > 0) {
            cy.nodes().forEach((n) => {
              if (suspiciousIds.has(n.id())) {
                n.style("border-width", 4);
                n.flashClass("suspicious", 1800);
              }
            });
          }
        }
      });
    } catch (e) {
      console.error("CytoscapeGraph: init failed", e);
    }

    return () => {
      if (pulseIntervalRef.current) {
        clearInterval(pulseIntervalRef.current);
        pulseIntervalRef.current = null;
      }
      if (cyRef.current) {
        try { cyRef.current.destroy(); } catch { /* ignore */ }
        cyRef.current = null;
      }
    };
  }, [data, buildElements, onNodeClick, layoutHint, egoMode, centerId, findSuspiciousSubgraph]);

  // ── Zoom control handlers (use ref so buttons always get latest cy) ───
  const zoomIn    = () => { if (cyRef.current) try { cyRef.current.zoom(cyRef.current.zoom() * 1.3); } catch { /* */ } };
  const zoomOut   = () => { if (cyRef.current) try { cyRef.current.zoom(cyRef.current.zoom() / 1.3); } catch { /* */ } };
  const fitScreen = () => { if (cyRef.current) try { cyRef.current.fit(undefined, 30); } catch { /* */ } };
  const resetView = () => { if (cyRef.current) try { cyRef.current.reset(); } catch { /* */ } };

  if (!data || data.nodes.length === 0) {
    return (
      <div className={`flex items-center justify-center h-full text-slate-500 ${className}`}>
        <p className="text-sm">No graph data to display</p>
      </div>
    );
  }

  return (
    <div className={`relative w-full h-full ${className}`}>
      {/* Cytoscape canvas */}
      <div ref={containerRef} className="w-full h-full bg-[#0b1120]" />

      {/* ── Zoom controls — top-right ─────────────────────────────────── */}
      <div className="absolute top-3 right-3 z-20 flex flex-col items-center gap-0.5 bg-slate-900/80 backdrop-blur border border-slate-700 rounded-lg p-1.5">
        <button
          onClick={zoomIn}
          title="Zoom In"
          className="w-7 h-7 flex items-center justify-center text-slate-300 hover:text-white hover:bg-slate-700 rounded text-base font-bold transition leading-none"
        >+</button>
        <button
          onClick={zoomOut}
          title="Zoom Out"
          className="w-7 h-7 flex items-center justify-center text-slate-300 hover:text-white hover:bg-slate-700 rounded text-base font-bold transition leading-none"
        >−</button>
        <div className="w-5 border-t border-slate-700 my-0.5" />
        <button
          onClick={fitScreen}
          title="Fit to Screen"
          className="w-7 h-7 flex items-center justify-center text-slate-300 hover:text-white hover:bg-slate-700 rounded text-xs transition"
        >⊡</button>
        <button
          onClick={resetView}
          title="Reset View"
          className="w-7 h-7 flex items-center justify-center text-slate-300 hover:text-white hover:bg-slate-700 rounded text-xs transition"
        >↺</button>
      </div>

      {/* ── Color legend — bottom-left ────────────────────────────────── */}
      <div className="absolute bottom-3 left-3 z-20 bg-slate-900/80 backdrop-blur border border-slate-700 rounded-lg px-3 py-2 space-y-1 pointer-events-none">
        <p className="text-[10px] font-semibold text-slate-400 mb-1 uppercase tracking-wider">Risk</p>
        {(
          [
            { color: "#ef4444", label: "CRITICAL" },
            { color: "#f97316", label: "HIGH" },
            { color: "#eab308", label: "MEDIUM" },
            { color: "#22c55e", label: "LOW" },
          ] as const
        ).map(({ color, label }) => (
          <div key={label} className="flex items-center gap-2">
            <span
              className="w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ backgroundColor: color }}
            />
            <span className="text-[10px] text-slate-400">{label}</span>
          </div>
        ))}
        {egoMode && (
          <>
            <div className="border-t border-slate-700/50 mt-1 pt-1 space-y-1">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full flex-shrink-0 border-2 border-white bg-blue-500" />
                <span className="text-[10px] text-slate-400">Center</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 border-2 border-orange-500 bg-transparent" />
                <span className="text-[10px] text-slate-400">1st-hop</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full flex-shrink-0 border border-slate-500 bg-transparent" />
                <span className="text-[10px] text-slate-400">2nd-hop</span>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
