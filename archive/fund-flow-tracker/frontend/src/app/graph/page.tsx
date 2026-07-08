"use client";

import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
  Suspense,
  lazy,
} from "react";
import { useSearchParams } from "next/navigation";
import { api, GraphData, GraphNode, GraphEdge } from "@/lib/api";
import { Card, Loader, Badge, InfoTooltip } from "@/components/ui";
import { formatINR, getRiskBg, getRoleIcon } from "@/lib/utils";

const CytoscapeGraph = lazy(() => import("@/components/CytoscapeGraph"));

interface SimNode extends GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  fixed?: boolean;
}

interface FundTrail {
  trail_count?: number;
  component_size?: number;
  trails?: Record<string, unknown>[][];
  error?: string;
}

interface Accomplice {
  account_id: string;
  visit_probability: number;
  risk_score: number;
  risk_level: string;
  role: string;
}

function AIExplanationPanel({ accountId }: { accountId: string }) {
  const [explanation, setExplanation] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [shown, setShown] = useState(false);

  const generate = async () => {
    if (shown && explanation) { setShown(false); return; }
    setShown(true);
    if (explanation) return;
    setLoading(true);
    try {
      const res = await api.getAccountExplanation(accountId);
      setExplanation(res.explanation);
    } catch {
      setExplanation("Could not generate explanation. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mt-2">
      <button
        onClick={generate}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-violet-600/20 border border-violet-500/30 text-xs text-violet-300 hover:bg-violet-600/30 transition-colors"
      >
        <span>🤖</span>
        <span>{shown && explanation ? "Hide Explanation" : "Why flagged? (AI)"}</span>
      </button>
      {shown && (
        <div className="mt-2 p-3 rounded-lg bg-violet-500/5 border border-violet-500/20">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-violet-300">
              <span className="h-3 w-3 border border-violet-400/40 border-t-violet-400 rounded-full animate-spin" />
              Generating AI explanation...
            </div>
          ) : (
            <p className="text-xs text-slate-300 leading-relaxed">{explanation}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function GraphExplorerPage() {
  return (
    <Suspense fallback={<Loader />}>
      <GraphExplorerContent />
    </Suspense>
  );
}

function GraphExplorerContent() {
  const searchParams    = useSearchParams();
  const initialAccount  = searchParams.get("account") || "";

  // ── Canvas refs ──────────────────────────────────────────────────────────
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const animRef      = useRef<number>(0);
  const nodesRef     = useRef<SimNode[]>([]);
  const edgesRef     = useRef<GraphEdge[]>([]);
  const hoveredRef   = useRef<SimNode | null>(null);
  const selectedRef  = useRef<SimNode | null>(null);
  const dragRef      = useRef<SimNode | null>(null);
  const panRef       = useRef({ x: 0, y: 0, startX: 0, startY: 0, panning: false });
  const zoomRef      = useRef(1);
  const mouseRef     = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const iterRef      = useRef(0);

  // ── State ────────────────────────────────────────────────────────────────
  const [searchId,          setSearchId]          = useState(initialAccount);
  const [maxNodes,          setMaxNodes]          = useState(40);
  const [viewMode,          setViewMode]          = useState<"network" | "ego" | "pattern">("network");
  const [hopDepth,          setHopDepth]          = useState(2);
  const [loading,           setLoading]           = useState(false);
  const [error,             setError]             = useState<string | null>(null);
  const [selectedNode,      setSelectedNode]      = useState<SimNode | null>(null);
  const [trailResult,       setTrailResult]       = useState<FundTrail | null>(null);
  const [accomplices,       setAccomplices]       = useState<Accomplice[] | null>(null);
  const [trailLoading,      setTrailLoading]      = useState(false);
  const [accompliceLoading, setAccompliceLoading] = useState(false);
  const [showLabels,        setShowLabels]        = useState(true);
  const [showAmounts,       setShowAmounts]       = useState(true);
  const [nodeCount,         setNodeCount]         = useState(0);
  const [edgeCount,         setEdgeCount]         = useState(0);
  const [riskFilter,        setRiskFilter]        = useState<string>("ALL");
  const [roleFilter,        setRoleFilter]        = useState<string>("ALL");
  const [patternFilter,     setPatternFilter]     = useState<string>("");
  const [patternViewType,   setPatternViewType]   = useState<string>("layering");
  const [rendererMode,      setRendererMode]      = useState<"canvas" | "cytoscape">("cytoscape");
  const [graphData,         setGraphData]         = useState<GraphData | null>(null);
  const [summaryOpen,       setSummaryOpen]       = useState(false);

  // ── Derived ───────────────────────────────────────────────────────────────
  const filtersActive = riskFilter !== "ALL" || roleFilter !== "ALL" || !!patternFilter;

  const clearFilters = useCallback(() => {
    setRiskFilter("ALL");
    setRoleFilter("ALL");
    setPatternFilter("");
  }, []);

  // ── Investigation summary (computed from graphData) ───────────────────────
  const investigationSummary = useMemo(() => {
    if (!graphData || !graphData.nodes || graphData.nodes.length === 0) return null;
    const nodes = graphData.nodes;
    const edges = graphData.edges || [];

    const totalValue    = edges.reduce((s, e) => s + (e.amount || 0), 0);
    const criticalCount = nodes.filter((n) => n.risk_level === "CRITICAL").length;
    const highCount     = nodes.filter((n) => n.risk_level === "HIGH").length;

    const inDeg  = new Map<string, number>(nodes.map((n) => [n.id, 0]));
    const outDeg = new Map<string, number>(nodes.map((n) => [n.id, 0]));
    for (const e of edges) {
      outDeg.set(e.source, (outDeg.get(e.source) || 0) + 1);
      inDeg.set(e.target,  (inDeg.get(e.target)  || 0) + 1);
    }

    const fanOutNodes = nodes
      .filter((n) => (outDeg.get(n.id) || 0) >= 5)
      .sort((a, b) => (outDeg.get(b.id) || 0) - (outDeg.get(a.id) || 0))
      .slice(0, 3);
    const fanInNodes = nodes
      .filter((n) => (inDeg.get(n.id) || 0) >= 5)
      .sort((a, b) => (inDeg.get(b.id) || 0) - (inDeg.get(a.id) || 0))
      .slice(0, 3);

    let hubNode = nodes[0];
    let maxDeg  = 0;
    for (const n of nodes) {
      const deg = (inDeg.get(n.id) || 0) + (outDeg.get(n.id) || 0);
      if (deg > maxDeg) { maxDeg = deg; hubNode = n; }
    }

    // Circular flows: bidirectional edge pairs
    const edgeSet = new Set(edges.map((e) => `${e.source}->${e.target}`));
    let circularCount = 0;
    for (const e of edges) {
      if (edgeSet.has(`${e.target}->${e.source}`)) circularCount++;
    }
    circularCount = Math.floor(circularCount / 2);

    return {
      totalValue,
      criticalCount,
      highCount,
      fanOutNodes,
      fanInNodes,
      hubNode,
      maxDeg,
      circularCount,
      nodeCount: nodes.length,
      edgeCount: edges.length,
    };
  }, [graphData]);

  // ── initSimulation (canvas mode) ──────────────────────────────────────────
  const initSimulation = useCallback((data: GraphData) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const w  = canvas.width;
    const h  = canvas.height;
    const cx = w / 2, cy = h / 2;
    const r  = Math.min(w, h) * 0.42;

    const nodes: SimNode[] = data.nodes.map((n, i) => {
      const angle = (2 * Math.PI * i) / data.nodes.length;
      return {
        ...n,
        x:      cx + r * Math.cos(angle),
        y:      cy + r * Math.sin(angle),
        vx:     0,
        vy:     0,
        radius: Math.max(14, Math.min(30, 14 + n.risk_score / 6)),
      };
    });

    nodesRef.current = nodes;
    edgesRef.current = data.edges;
    iterRef.current  = 0;
    panRef.current   = { x: 0, y: 0, startX: 0, startY: 0, panning: false };
    zoomRef.current  = 1;
    setNodeCount(nodes.length);
    setEdgeCount(data.edges.length);
  }, []);

  // ── loadGraph ─────────────────────────────────────────────────────────────
  const loadGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    setTrailResult(null);
    setAccomplices(null);
    setSelectedNode(null);
    selectedRef.current = null;

    try {
      let data: GraphData;

      if (viewMode === "pattern") {
        data = await api.getPatternGraph(patternViewType, maxNodes);
      } else if (viewMode === "ego" && searchId.trim()) {
        data = await api.getEgoGraph(searchId.trim(), hopDepth);
      } else if (riskFilter !== "ALL" || roleFilter !== "ALL" || patternFilter) {
        const riskRanges: Record<string, [number, number]> = {
          CRITICAL: [76, 100],
          HIGH:     [51, 75],
          MEDIUM:   [26, 50],
          LOW:      [0,  25],
          ALL:      [0, 100],
        };
        const [risk_min, risk_max] = riskRanges[riskFilter] || [0, 100];
        data = await api.getGraphFiltered({
          risk_min,
          risk_max,
          max_nodes: maxNodes,
          role:      roleFilter !== "ALL" ? roleFilter : undefined,
          pattern:   patternFilter || undefined,
        });
      } else {
        data = await api.getGraph(maxNodes);
      }

      if (!data || !data.nodes) data = { nodes: [], edges: [] };
      if (!data.edges)          data.edges = [];

      initSimulation(data);
      setGraphData(data);
      setNodeCount(data.nodes?.length || 0);
      setEdgeCount(data.edges?.length || 0);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load graph";
      if (msg.includes("503") || msg.includes("not initialized")) {
        setError("No data loaded yet. Upload transaction data on the Ingest page first.");
      } else {
        setError(msg);
      }
      setGraphData({ nodes: [], edges: [] });
    } finally {
      setLoading(false);
    }
  }, [
    viewMode, searchId, hopDepth, maxNodes,
    riskFilter, roleFilter, patternFilter, patternViewType,
    initSimulation,
  ]);

  // ── Stable ref to loadGraph — used by debounced auto-reload effects ───────
  const loadGraphRef = useRef<() => Promise<void>>(async () => {});
  useEffect(() => { loadGraphRef.current = loadGraph; }, [loadGraph]);

  // ── Initial load ──────────────────────────────────────────────────────────
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      loadGraph();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auto-reload when filter dropdowns change (skip initial mount) ─────────
  const filtersMountedRef = useRef(false);
  useEffect(() => {
    if (!filtersMountedRef.current) {
      filtersMountedRef.current = true;
      return;
    }
    const timer = setTimeout(() => { loadGraphRef.current(); }, 300);
    return () => clearTimeout(timer);
  }, [riskFilter, roleFilter, patternFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Auto-reload when maxNodes slider changes (500 ms debounce) ───────────
  const sliderMountedRef = useRef(false);
  useEffect(() => {
    if (!sliderMountedRef.current) {
      sliderMountedRef.current = true;
      return;
    }
    const timer = setTimeout(() => { loadGraphRef.current(); }, 500);
    return () => clearTimeout(timer);
  }, [maxNodes]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Canvas resize ─────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const resize = () => {
      const parent = canvas.parentElement;
      if (parent) {
        canvas.width  = parent.clientWidth;
        canvas.height = parent.clientHeight;
      }
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  // ── Canvas animation loop ─────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const tick = () => {
      const nodes  = nodesRef.current;
      const edges  = edgesRef.current;
      const w      = canvas.width;
      const h      = canvas.height;
      const zoom   = zoomRef.current;
      const pan    = panRef.current;

      iterRef.current++;
      const cooling      = Math.max(0.01, 1 - iterRef.current / 400);
      const damping      = 0.82;
      const repulsion    = 8000 * cooling;
      const attraction   = 0.004 * cooling;
      const centerGravity = 0.003 * cooling;

      const lookup = new Map<string, SimNode>();
      for (const n of nodes) lookup.set(n.id, n);

      if (cooling > 0.02) {
        for (let i = 0; i < nodes.length; i++) {
          if (nodes[i].fixed) continue;
          let fx = 0, fy = 0;
          fx += (w / 2 - nodes[i].x) * centerGravity;
          fy += (h / 2 - nodes[i].y) * centerGravity;
          for (let j = 0; j < nodes.length; j++) {
            if (i === j) continue;
            const dx   = nodes[i].x - nodes[j].x;
            const dy   = nodes[i].y - nodes[j].y;
            const dist = Math.sqrt(dx * dx + dy * dy) || 1;
            if (dist < 600) {
              const force = repulsion / (dist * dist);
              fx += (dx / dist) * force;
              fy += (dy / dist) * force;
            }
          }
          for (const edge of edges) {
            let other: SimNode | undefined;
            if (edge.source === nodes[i].id) other = lookup.get(edge.target);
            else if (edge.target === nodes[i].id) other = lookup.get(edge.source);
            if (other) {
              const dx = other.x - nodes[i].x;
              const dy = other.y - nodes[i].y;
              fx += dx * attraction;
              fy += dy * attraction;
            }
          }
          nodes[i].vx = (nodes[i].vx + fx) * damping;
          nodes[i].vy = (nodes[i].vy + fy) * damping;
          nodes[i].x += nodes[i].vx;
          nodes[i].y += nodes[i].vy;
          nodes[i].x = Math.max(50, Math.min(w - 50, nodes[i].x));
          nodes[i].y = Math.max(50, Math.min(h - 50, nodes[i].y));
        }
      }

      ctx.fillStyle = "#0b1120";
      ctx.fillRect(0, 0, w, h);
      ctx.save();
      ctx.translate(pan.x, pan.y);
      ctx.scale(zoom, zoom);

      // Edges
      for (const edge of edges) {
        const src = lookup.get(edge.source);
        const tgt = lookup.get(edge.target);
        if (!src || !tgt) continue;
        const dx    = tgt.x - src.x;
        const dy    = tgt.y - src.y;
        const dist  = Math.sqrt(dx * dx + dy * dy) || 1;
        const angle = Math.atan2(dy, dx);
        const alpha = edge.amount > 100000 ? 0.7 : 0.4;
        ctx.strokeStyle = `rgba(100, 160, 200, ${alpha})`;
        ctx.lineWidth   = Math.max(1, Math.min(3.5, edge.amount / 150000));
        ctx.beginPath();
        ctx.moveTo(src.x, src.y);
        ctx.lineTo(tgt.x, tgt.y);
        ctx.stroke();
        const arrowLen = 8;
        const ax = tgt.x - Math.cos(angle) * (tgt.radius + 3);
        const ay = tgt.y - Math.sin(angle) * (tgt.radius + 3);
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(ax - arrowLen * Math.cos(angle - 0.35), ay - arrowLen * Math.sin(angle - 0.35));
        ctx.lineTo(ax - arrowLen * Math.cos(angle + 0.35), ay - arrowLen * Math.sin(angle + 0.35));
        ctx.closePath();
        ctx.fillStyle = `rgba(100, 140, 180, ${alpha + 0.2})`;
        ctx.fill();
        if (showAmounts && zoom > 0.5 && dist > 60) {
          const mx       = (src.x + tgt.x) / 2;
          const my       = (src.y + tgt.y) / 2;
          const fontSize = Math.max(10, Math.round(11 / zoom));
          ctx.font       = `${fontSize}px monospace`;
          const label    = formatINR(edge.amount);
          const tw       = ctx.measureText(label).width;
          ctx.fillStyle  = "rgba(11, 17, 32, 0.7)";
          ctx.fillRect(mx - tw / 2 - 3, my - fontSize - 2, tw + 6, fontSize + 4);
          ctx.fillStyle  = "rgba(148, 180, 210, 0.85)";
          ctx.textAlign  = "center";
          ctx.fillText(label, mx, my - 4);
        }
      }

      // Nodes
      let hovered: SimNode | null = null;
      const mx = (mouseRef.current.x - pan.x) / zoom;
      const my = (mouseRef.current.y - pan.y) / zoom;
      for (const node of nodes) {
        const dx = mx - node.x;
        const dy = my - node.y;
        if (Math.sqrt(dx * dx + dy * dy) < node.radius + 3) hovered = node;
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        const grad = ctx.createRadialGradient(node.x - 2, node.y - 2, 0, node.x, node.y, node.radius);
        grad.addColorStop(0, node.risk_color || "#6366f1");
        grad.addColorStop(1, "rgba(0,0,0,0.3)");
        ctx.fillStyle = grad;
        ctx.fill();
        if (selectedRef.current?.id === node.id) {
          ctx.strokeStyle = "#ffffff";
          ctx.lineWidth   = 3;
          ctx.stroke();
        } else if (hovered?.id === node.id) {
          ctx.strokeStyle = "rgba(255,255,255,0.6)";
          ctx.lineWidth   = 2;
          ctx.stroke();
        }
        if (showLabels && zoom > 0.35) {
          const fontSize = Math.max(12, Math.round(13 / zoom));
          ctx.font       = `bold ${Math.min(fontSize, 16)}px monospace`;
          ctx.textAlign  = "center";
          const label    = node.id.replace("ACC_", "");
          const tw       = ctx.measureText(label).width;
          ctx.fillStyle  = "rgba(11, 17, 32, 0.8)";
          ctx.fillRect(node.x - tw / 2 - 4, node.y + node.radius + 2, tw + 8, fontSize + 6);
          ctx.fillStyle  = "#f1f5f9";
          ctx.fillText(label, node.x, node.y + node.radius + fontSize + 2);
          if (node.role !== "NORMAL") {
            const roleSize = Math.min(fontSize - 1, 12);
            ctx.font       = `bold ${roleSize}px sans-serif`;
            ctx.fillStyle  = node.role === "MULE" ? "#eab308" : node.role === "SOURCE" ? "#ef4444" : "#8b5cf6";
            ctx.fillText(node.role, node.x, node.y + node.radius + fontSize + roleSize + 6);
          }
        }
      }

      hoveredRef.current = hovered;

      // Tooltip
      if (hovered) {
        ctx.restore();
        const tx    = mouseRef.current.x + 15;
        const ty    = mouseRef.current.y - 10;
        const lines = [
          `${hovered.id}`,
          `Risk: ${hovered.risk_score.toFixed(1)} (${hovered.risk_level})`,
          `Role: ${hovered.role}`,
        ];
        const lineH = 16, pad = 10;
        ctx.font    = "12px monospace";
        const maxW  = Math.max(...lines.map((l) => ctx.measureText(l).width));
        const boxW  = maxW + pad * 2;
        const boxH  = lineH * lines.length + pad * 2;
        ctx.fillStyle   = "rgba(15, 23, 42, 0.95)";
        ctx.strokeStyle = "rgba(71, 85, 105, 0.5)";
        ctx.lineWidth   = 1;
        ctx.beginPath();
        ctx.roundRect(tx, ty - pad, boxW, boxH, 6);
        ctx.fill();
        ctx.stroke();
        lines.forEach((line, i) => {
          ctx.fillStyle = i === 0 ? "#60a5fa" : "#e2e8f0";
          ctx.fillText(line, tx + pad, ty + lineH * (i + 0.5));
        });
      } else {
        ctx.restore();
      }

      // Canvas legend
      ctx.font      = "11px sans-serif";
      ctx.fillStyle = "#64748b";
      ctx.textAlign = "left";
      [
        { color: "#ef4444", label: "CRITICAL" },
        { color: "#f97316", label: "HIGH" },
        { color: "#eab308", label: "MEDIUM" },
        { color: "#22c55e", label: "LOW" },
      ].forEach((item, i) => {
        const lx = 12, ly = h - 80 + i * 18;
        ctx.beginPath();
        ctx.arc(lx + 5, ly, 4, 0, Math.PI * 2);
        ctx.fillStyle = item.color;
        ctx.fill();
        ctx.fillStyle = "#94a3b8";
        ctx.fillText(item.label, lx + 14, ly + 4);
      });

      animRef.current = requestAnimationFrame(tick);
    };

    animRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(animRef.current);
  }, [showLabels, showAmounts]);

  // ── Canvas mouse events ────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const handleMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouseRef.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
      if (dragRef.current) {
        const zoom = zoomRef.current, pan = panRef.current;
        dragRef.current.x  = (mouseRef.current.x - pan.x) / zoom;
        dragRef.current.y  = (mouseRef.current.y - pan.y) / zoom;
        dragRef.current.vx = 0;
        dragRef.current.vy = 0;
        return;
      }
      if (panRef.current.panning) {
        panRef.current.x = mouseRef.current.x - panRef.current.startX;
        panRef.current.y = mouseRef.current.y - panRef.current.startY;
      }
    };
    const handleDown = (e: MouseEvent) => {
      if (hoveredRef.current) {
        dragRef.current       = hoveredRef.current;
        dragRef.current.fixed = true;
      } else {
        panRef.current.panning = true;
        panRef.current.startX  = mouseRef.current.x - panRef.current.x;
        panRef.current.startY  = mouseRef.current.y - panRef.current.y;
      }
    };
    const handleUp = () => {
      if (dragRef.current) { dragRef.current.fixed = false; dragRef.current = null; }
      panRef.current.panning = false;
    };
    const handleClick = () => {
      if (hoveredRef.current && !panRef.current.panning) {
        selectedRef.current = hoveredRef.current;
        setSelectedNode({ ...hoveredRef.current });
        setSearchId(hoveredRef.current.id);
        setViewMode("ego");
      }
    };
    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      const factor    = e.deltaY > 0 ? 0.92 : 1.08;
      zoomRef.current = Math.max(0.2, Math.min(4, zoomRef.current * factor));
    };
    canvas.addEventListener("mousemove",  handleMove);
    canvas.addEventListener("mousedown",  handleDown);
    canvas.addEventListener("mouseup",    handleUp);
    canvas.addEventListener("click",      handleClick);
    canvas.addEventListener("wheel",      handleWheel, { passive: false });
    return () => {
      canvas.removeEventListener("mousemove",  handleMove);
      canvas.removeEventListener("mousedown",  handleDown);
      canvas.removeEventListener("mouseup",    handleUp);
      canvas.removeEventListener("click",      handleClick);
      canvas.removeEventListener("wheel",      handleWheel);
    };
  }, []);

  // ── Action handlers ───────────────────────────────────────────────────────
  const handleFundTrail = async () => {
    const id = selectedNode?.id || searchId.trim();
    if (!id) return;
    setTrailLoading(true);
    setTrailResult(null);
    try {
      const result = await api.getFundTrail(id);
      setTrailResult(result);
    } catch (e: unknown) {
      setTrailResult({ error: e instanceof Error ? e.message : "Failed" });
    } finally {
      setTrailLoading(false);
    }
  };

  const handleFindAccomplices = async () => {
    const id = selectedNode?.id || searchId.trim();
    if (!id) return;
    setAccompliceLoading(true);
    setAccomplices(null);
    try {
      const result = await api.getRandomWalk(id);
      setAccomplices(result.accomplices);
    } catch {
      setAccomplices([]);
    } finally {
      setAccompliceLoading(false);
    }
  };

  const handleRecenter = () => {
    panRef.current  = { x: 0, y: 0, startX: 0, startY: 0, panning: false };
    zoomRef.current = 1;
  };

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-[calc(100vh-56px)] gap-0 bg-[#0b1120]">

      {/* ── Left Control Panel ────────────────────────────────────────────── */}
      <div className="w-64 flex-shrink-0 flex flex-col gap-2 overflow-y-auto p-3 border-r border-slate-700/30 bg-[#0f172a]/50">
        <div className="text-sm font-semibold text-slate-300 px-1">Graph Explorer</div>

        {/* Account search */}
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Account ID</label>
          <input
            type="text"
            value={searchId}
            onChange={(e) => setSearchId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && loadGraph()}
            placeholder="e.g. ACC_0200"
            className="w-full mt-1 px-2.5 py-1.5 bg-slate-800 border border-slate-700 rounded text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500"
          />
        </div>

        {/* View mode */}
        <div className="flex gap-1">
          {(["network", "ego", "pattern"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setViewMode(mode)}
              className={`flex-1 px-2 py-1.5 text-[10px] font-medium rounded transition capitalize ${
                viewMode === mode
                  ? mode === "pattern" ? "bg-purple-600 text-white" : "bg-blue-600 text-white"
                  : "bg-slate-800 text-slate-400 hover:bg-slate-700"
              }`}
            >
              {mode === "pattern" ? "Patterns" : mode.charAt(0).toUpperCase() + mode.slice(1)}
            </button>
          ))}
        </div>

        {/* Pattern type */}
        {viewMode === "pattern" && (
          <div>
            <label className="text-[10px] text-slate-500">Pattern Type</label>
            <select
              value={patternViewType}
              onChange={(e) => setPatternViewType(e.target.value)}
              className="w-full mt-0.5 px-2 py-1.5 bg-slate-800 border border-slate-700 rounded text-xs text-slate-200 focus:outline-none focus:border-blue-500"
            >
              <option value="layering">🔗 Layering Chains</option>
              <option value="round_trip">🔄 Round-Trip Cycles</option>
              <option value="structuring">💰 Structuring</option>
              <option value="dormancy">💤 Dormancy Burst</option>
              <option value="profile_mismatch">👤 Profile Mismatch</option>
            </select>
          </div>
        )}

        {/* Max Nodes slider */}
        {viewMode === "network" && (
          <div>
            <label className="text-[10px] text-slate-500">
              Max Nodes: <span className="text-slate-300">{maxNodes}</span> <InfoTooltip text="Maximum number of accounts to display. Accounts are ranked by risk score — highest risk accounts appear first. Increase to see more of the network (may slow rendering)." />
            </label>
            <input
              type="range" min={20} max={200} value={maxNodes}
              onChange={(e) => setMaxNodes(Number(e.target.value))}
              className="w-full mt-1 accent-blue-500 h-1"
            />
          </div>
        )}

        {/* Hop depth */}
        {viewMode === "ego" && (
          <div>
            <label className="text-[10px] text-slate-500">
              Hop Depth: <span className="text-slate-300">{hopDepth}</span> <InfoTooltip text="Ego Graph radius: 1 = only direct counterparties, 2 = counterparties of counterparties (recommended). Higher values can produce very large graphs." />
            </label>
            <input
              type="range" min={1} max={4} value={hopDepth}
              onChange={(e) => setHopDepth(Number(e.target.value))}
              className="w-full mt-1 accent-blue-500 h-1"
            />
          </div>
        )}

        {/* Display options */}
        <div className="flex items-center gap-3 text-[10px]">
          <label className="flex items-center gap-1.5 text-slate-400 cursor-pointer">
            <input type="checkbox" checked={showLabels}  onChange={(e) => setShowLabels(e.target.checked)}  className="accent-blue-500" />
            Labels
          </label>
          <label className="flex items-center gap-1.5 text-slate-400 cursor-pointer">
            <input type="checkbox" checked={showAmounts} onChange={(e) => setShowAmounts(e.target.checked)} className="accent-blue-500" />
            Amounts
          </label>
        </div>

        {/* Renderer */}
        <div>
          <label className="text-[10px] text-slate-500 uppercase tracking-wider">Renderer</label>
          <div className="flex gap-1 mt-1">
            {(["cytoscape", "canvas"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRendererMode(r)}
                className={`flex-1 px-2 py-1.5 text-[10px] font-medium rounded transition capitalize ${
                  rendererMode === r ? "bg-emerald-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"
                }`}
              >
                {r.charAt(0).toUpperCase() + r.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Filters */}
        <div className="border-t border-slate-700/50 pt-2 mt-1">
          <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Filters</div>
          <div className="space-y-1.5">
            <div>
              <label className="text-[10px] text-slate-500">Risk Level <InfoTooltip text="Filter the graph to show only accounts at or above this risk level. Selecting HIGH shows HIGH and CRITICAL accounts only." /></label>
              <select
                value={riskFilter}
                onChange={(e) => setRiskFilter(e.target.value)}
                className="w-full mt-0.5 px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs text-slate-200 focus:outline-none focus:border-blue-500"
              >
                <option value="ALL">All Levels</option>
                <option value="CRITICAL">Critical (76–100)</option>
                <option value="HIGH">High (51–75)</option>
                <option value="MEDIUM">Medium (26–50)</option>
                <option value="LOW">Low (0–25)</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-slate-500">Role <InfoTooltip text="Filter by the account's detected network role: MULE (recipient-forwarder), COLLECTOR (aggregator), SMURFER (structured deposits), TRANSIENT (brief appearance), SOURCE (originator), SINK (final destination)." /></label>
              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                className="w-full mt-0.5 px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs text-slate-200 focus:outline-none focus:border-blue-500"
              >
                <option value="ALL">All Roles</option>
                <option value="MULE">Mule</option>
                <option value="SOURCE">Source</option>
                <option value="SINK">Sink</option>
                <option value="NORMAL">Normal</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] text-slate-500">Pattern <InfoTooltip text="Show only accounts flagged for this specific AML typology. The graph will display only the flagged accounts and their direct connections." /></label>
              <select
                value={patternFilter}
                onChange={(e) => setPatternFilter(e.target.value)}
                className="w-full mt-0.5 px-2 py-1 bg-slate-800 border border-slate-700 rounded text-xs text-slate-200 focus:outline-none focus:border-blue-500"
              >
                <option value="">All Patterns</option>
                <option value="layering">Layering</option>
                <option value="round_trip">Round Trip</option>
                <option value="structuring">Structuring</option>
                <option value="dormancy">Dormancy</option>
                <option value="profile_mismatch">Profile Mismatch</option>
              </select>
            </div>
          </div>
        </div>

        {/* Action buttons */}
        <div className="flex flex-col gap-1.5">
          <button onClick={loadGraph} className="w-full px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded transition font-medium">
            Load Graph
          </button>
          <button onClick={handleRecenter} className="w-full px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs rounded transition">
            Recenter
          </button>
          <button onClick={handleFundTrail} disabled={trailLoading} className="w-full px-3 py-1.5 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white text-xs rounded transition">
            {trailLoading ? "Tracing…" : "Trace Flow"}
          </button>
          <button onClick={handleFindAccomplices} disabled={accompliceLoading} className="w-full px-3 py-1.5 bg-orange-600 hover:bg-orange-700 disabled:opacity-50 text-white text-xs rounded transition">
            {accompliceLoading ? "Searching…" : "Find Accomplices"}
          </button>
        </div>

        {/* Stats */}
        <div className="text-[10px] text-slate-600 px-1">
          {nodeCount} nodes · {edgeCount} edges · Scroll to zoom · Drag to pan
        </div>

        {/* Trail results */}
        {trailResult && (
          <div className="bg-slate-800/50 rounded p-2 border border-slate-700/30">
            <div className="text-[10px] text-slate-400 font-medium mb-1">Fund Trail</div>
            {trailResult.error ? (
              <p className="text-[10px] text-red-400">{trailResult.error}</p>
            ) : (
              <>
                <div className="text-[10px] text-slate-500 mb-1">
                  {trailResult.trail_count} trails · Component: {trailResult.component_size}
                </div>
                <div className="space-y-1 max-h-40 overflow-y-auto">
                  {trailResult.trails?.slice(0, 5).map((trail, i) => (
                    <div key={i} className="text-[10px] bg-slate-900/50 rounded p-1.5 flex flex-wrap items-center gap-0.5">
                      {trail.map((hop: Record<string, unknown>, j: number) => (
                        <React.Fragment key={j}>
                          {j > 0 && <span className="text-slate-600">→</span>}
                          <span className="text-blue-400">
                            {String(hop.account_id || hop.node || hop.from || hop.to || hop.account || "N/A").replace("ACC_", "")}
                          </span>
                          {hop.amount != null && (
                            <span className="text-slate-600">({formatINR(Number(hop.amount))})</span>
                          )}
                        </React.Fragment>
                      ))}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}

        {/* Accomplice results */}
        {accomplices && (
          <div className="bg-slate-800/50 rounded p-2 border border-slate-700/30">
            <div className="text-[10px] text-slate-400 font-medium mb-0.5">Connected Accounts</div>
            <div className="text-[9px] text-slate-600 mb-1">Frequency in fund flow paths</div>
            {accomplices.length === 0 ? (
              <p className="text-[10px] text-slate-500">None found</p>
            ) : (
              <div className="space-y-0.5 max-h-40 overflow-y-auto">
                {accomplices.map((a) => (
                  <div key={a.account_id} className="flex items-center justify-between text-[10px] py-0.5">
                    <span className="text-blue-400 font-mono">{a.account_id.replace("ACC_", "")}</span>
                    <span className={`font-medium ${a.visit_probability >= 0.1 ? "text-red-400" : a.visit_probability >= 0.02 ? "text-amber-400" : "text-slate-400"}`}>
                      {a.visit_probability >= 0.1 ? "Strong" : a.visit_probability >= 0.02 ? "Moderate" : "Weak"}
                    </span>
                    <span className="text-slate-400">{a.role}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Main Canvas Area ──────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden bg-[#0b1120]">

        {/* Graph panel header */}
        <div className="flex-shrink-0 flex items-center justify-between px-3 py-2 border-b border-slate-700/30 bg-[#0f172a]/60">
          <span className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">Graph Canvas</span>
          {filtersActive && (
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-yellow-500/15 border border-yellow-500/30 text-yellow-400 font-medium">
                ⚠ Filters Active
              </span>
              <button
                onClick={() => { clearFilters(); }}
                className="text-[10px] px-2 py-0.5 rounded bg-slate-700/80 hover:bg-slate-600 border border-slate-600 text-slate-300 transition"
              >
                ✕ Clear All Filters
              </button>
            </div>
          )}
        </div>

        {/* Ego graph banner */}
        {viewMode === "ego" && searchId.trim() && graphData && graphData.nodes.length > 0 && (
          <div className="flex-shrink-0 flex items-center gap-2 px-3 py-1.5 bg-blue-950/40 border-b border-blue-500/20 text-[11px] text-blue-300">
            <span className="text-blue-500">◉</span>
            <span>Ego Graph:</span>
            <span className="font-mono text-blue-400 font-medium">{searchId.trim()}</span>
            <span className="text-blue-500/50">·</span>
            <span>{Math.max(0, graphData.nodes.length - 1)} neighbors</span>
            <span className="text-blue-500/50">·</span>
            <span>{hopDepth}-hop radius</span>
          </div>
        )}

        {/* Investigation summary (collapsible) */}
        {investigationSummary && (
          <div className="flex-shrink-0 border-b border-slate-700/30 bg-[#0f172a]/40">
            <button
              onClick={() => setSummaryOpen((o) => !o)}
              className="w-full flex items-center justify-between px-3 py-1.5 text-[10px] font-semibold text-slate-400 hover:text-slate-200 uppercase tracking-wider transition"
            >
              <span className="flex items-center gap-1.5">
                <span className="text-slate-500">▶</span>
                Investigation Summary
              </span>
              <span className="text-slate-600 normal-case font-normal">
                {summaryOpen ? "▲ collapse" : "▼ expand"}
              </span>
            </button>

            {summaryOpen && (
              <div className="px-3 pb-3 space-y-2">
                {/* Narrative */}
                <p className="text-[11px] text-slate-300 leading-relaxed bg-slate-900/60 rounded p-2.5 border border-slate-700/30">
                  This subgraph contains{" "}
                  <span className="text-white font-medium">{investigationSummary.nodeCount} accounts</span> and{" "}
                  <span className="text-white font-medium">{investigationSummary.edgeCount} transactions</span> totaling{" "}
                  <span className="text-emerald-400 font-medium">{formatINR(investigationSummary.totalValue)}</span>.
                  {investigationSummary.criticalCount > 0 && (
                    <> <span className="text-red-400 font-medium">{investigationSummary.criticalCount} accounts</span> are flagged CRITICAL risk.</>
                  )}
                  {investigationSummary.hubNode && investigationSummary.maxDeg > 1 && (
                    <> Account <span className="text-blue-400 font-mono">{investigationSummary.hubNode.id.replace("ACC_", "")}</span> is a key hub with{" "}
                    <span className="text-white font-medium">{investigationSummary.maxDeg} connections</span>.</>
                  )}
                  {investigationSummary.circularCount > 0 && (
                    <> <span className="text-amber-400 font-medium">{investigationSummary.circularCount} potential circular flows</span> detected.</>
                  )}
                  {investigationSummary.fanOutNodes.length > 0 && (
                    <> Fan-out pattern from <span className="text-orange-400 font-medium">{investigationSummary.fanOutNodes.length} account{investigationSummary.fanOutNodes.length > 1 ? "s" : ""}</span> suggests layering.</>
                  )}
                </p>

                {/* Stat chips */}
                <div className="flex flex-wrap gap-1.5">
                  {[
                    { label: "Accounts",        val: investigationSummary.nodeCount,     color: "text-blue-400",   bg: "bg-blue-500/10 border-blue-500/20" },
                    { label: "Transactions",    val: investigationSummary.edgeCount,     color: "text-slate-300",  bg: "bg-slate-700/40 border-slate-600/30" },
                    { label: "Total Value",     val: formatINR(investigationSummary.totalValue), color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20" },
                    { label: "Critical",        val: investigationSummary.criticalCount, color: "text-red-400",    bg: "bg-red-500/10 border-red-500/20" },
                    { label: "High",            val: investigationSummary.highCount,     color: "text-orange-400", bg: "bg-orange-500/10 border-orange-500/20" },
                    { label: "Circular Flows",  val: investigationSummary.circularCount, color: "text-amber-400",  bg: "bg-amber-500/10 border-amber-500/20" },
                  ].map(({ label, val, color, bg }) => (
                    <div
                      key={label}
                      className={`flex flex-col items-center px-2.5 py-1.5 rounded border ${bg} min-w-[70px]`}
                    >
                      <span className={`text-sm font-bold ${color}`}>{val}</span>
                      <span className="text-[9px] text-slate-500 uppercase tracking-wider mt-0.5">{label}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Canvas / Cytoscape area — fills remaining space */}
        <div className="flex-1 relative overflow-hidden">
          {loading && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#0b1120]/80">
              <Loader />
            </div>
          )}
          {error && (
            <div className="absolute top-3 left-3 z-10 bg-red-500/20 border border-red-500/30 rounded px-3 py-2 text-xs text-red-400">
              {error}
            </div>
          )}

          {rendererMode === "cytoscape" ? (
            <Suspense fallback={<Loader />}>
              <CytoscapeGraph
                data={graphData}
                onNodeClick={(nodeId) => {
                  setSearchId(nodeId);
                  setViewMode("ego");
                  const node = graphData?.nodes.find((n) => n.id === nodeId);
                  if (node) {
                    const simNode: SimNode = {
                      ...node,
                      x: 0, y: 0, vx: 0, vy: 0,
                      radius: Math.max(14, Math.min(30, 14 + node.risk_score / 6)),
                    };
                    setSelectedNode(simNode);
                    selectedRef.current = simNode;
                  }
                }}
                className="w-full h-full"
                layoutHint={
                  viewMode === "pattern"
                    ? patternViewType === "round_trip"  ? "circle"
                    : patternViewType === "layering"    ? "breadthfirst"
                    : "concentric"
                    : undefined
                }
                egoMode={viewMode === "ego"}
                centerId={viewMode === "ego" ? (searchId.trim() || undefined) : undefined}
              />
            </Suspense>
          ) : (
            <>
              <canvas ref={canvasRef} className="w-full h-full block cursor-crosshair" />
              {/* Canvas-mode legend */}
              <div className="absolute bottom-2 left-2 z-10 bg-[#1e293b]/95 backdrop-blur border border-slate-700/50 rounded-lg px-3 py-2 text-[10px] space-y-1.5 max-w-[280px]">
                <p className="font-semibold text-slate-300 text-xs mb-1">Legend</p>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[#ef4444]" />CRITICAL</span>
                  <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[#f97316]" />HIGH</span>
                  <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[#eab308]" />MEDIUM</span>
                  <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-[#22c55e]" />LOW</span>
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1 border-t border-slate-700/50">
                  <span className="flex items-center gap-1"><span className="w-0 h-0 border-l-[4px] border-r-[4px] border-b-[7px] border-transparent border-b-slate-300" />SOURCE</span>
                  <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rotate-45 bg-slate-300" />MULE</span>
                  <span className="flex items-center gap-1"><span className="w-0 h-0 border-l-[4px] border-r-[4px] border-t-[7px] border-transparent border-t-slate-300" />SINK</span>
                  <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-slate-300" />NORMAL</span>
                </div>
                <div className="pt-1 border-t border-slate-700/50 text-slate-500">
                  <p>Node size = risk score | Edge thickness = amount</p>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Right Detail Panel ────────────────────────────────────────────── */}
      {selectedNode && (
        <div className="w-64 flex-shrink-0 overflow-y-auto p-3 border-l border-slate-700/30 bg-[#0f172a]/50">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-slate-300">Node Details</h3>
            <button
              onClick={() => { setSelectedNode(null); selectedRef.current = null; }}
              className="text-slate-500 hover:text-slate-300 text-sm"
            >
              ✕
            </button>
          </div>

          <div className="space-y-3">
            <div>
              <p className="text-[10px] text-slate-500">Account ID</p>
              <p className="text-sm font-mono text-blue-400">{selectedNode.id}</p>
            </div>

            <div>
              <p className="text-[10px] text-slate-500">Risk Score</p>
              <div className="flex items-center gap-2 mt-1">
                <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width:           `${Math.min(selectedNode.risk_score, 100)}%`,
                      backgroundColor: selectedNode.risk_color,
                    }}
                  />
                </div>
                <span className="text-xs font-medium text-slate-200">{selectedNode.risk_score.toFixed(1)}</span>
              </div>
            </div>

            <div className="flex gap-3">
              <div>
                <p className="text-[10px] text-slate-500">Level</p>
                <Badge
                  variant={
                    selectedNode.risk_level === "CRITICAL" || selectedNode.risk_level === "HIGH"
                      ? "danger"
                      : selectedNode.risk_level === "MEDIUM"
                      ? "warning"
                      : "success"
                  }
                >
                  {selectedNode.risk_level}
                </Badge>
              </div>
              <div>
                <p className="text-[10px] text-slate-500">Role</p>
                <span className="text-xs">{getRoleIcon(selectedNode.role)} {selectedNode.role}</span>
              </div>
            </div>

            <div className="flex flex-col gap-1.5 pt-2 border-t border-slate-700/50">
              <button
                onClick={async () => {
                  const id = selectedNode.id;
                  setSearchId(id);
                  setViewMode("ego");
                  setLoading(true);
                  setError(null);
                  try {
                    const data     = await api.getEgoGraph(id, hopDepth);
                    const safeData = data && data.nodes ? data : { nodes: [], edges: [] };
                    initSimulation(safeData);
                    setGraphData(safeData);
                    setNodeCount(safeData.nodes?.length || 0);
                    setEdgeCount(safeData.edges?.length || 0);
                  } catch (e: unknown) {
                    setError(e instanceof Error ? e.message : "Failed to load ego graph");
                    setGraphData({ nodes: [], edges: [] });
                  } finally {
                    setLoading(false);
                  }
                }}
                className="w-full px-2.5 py-1.5 bg-blue-600/20 hover:bg-blue-600/30 text-blue-400 text-[10px] rounded border border-blue-500/30 transition"
              >
                Focus Ego Graph
              </button>
              <button
                onClick={() => handleFundTrail()}
                className="w-full px-2.5 py-1.5 bg-purple-600/20 hover:bg-purple-600/30 text-purple-400 text-[10px] rounded border border-purple-500/30 transition"
              >
                Trace Funds
              </button>
              <button
                onClick={() => handleFindAccomplices()}
                className="w-full px-2.5 py-1.5 bg-orange-600/20 hover:bg-orange-600/30 text-orange-400 text-[10px] rounded border border-orange-500/30 transition"
              >
                Find Accomplices
              </button>
            </div>

            <div className="mt-4 pt-4 border-t border-slate-700/50">
              <h4 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">AI Investigation Brief</h4>
              <AIExplanationPanel accountId={selectedNode.id} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
