"use client";

import type { Core, ElementDefinition, NodeSingular, StylesheetJsonBlock } from "cytoscape";
import { Pause, Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CytoscapeComponent from "react-cytoscapejs";

import { Button } from "@/components/ui/button";
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
import { readGraphTheme, truncate, type GraphTheme } from "@/components/workspace/deep/graph-theme";
import { formatDateTime } from "@/components/dashboard/format";
import { useTriageFetch } from "@/lib/workspace/use-triage-fetch";
import { TriageSection } from "@/components/workspace/triage/triage-section";
import type { TimelineEventItem, TimelineResponse } from "@/lib/api/types";

const SPEED_OPTIONS = [1, 2, 4, 8];
const BASE_STEP_MS = 700;

function buildElements(accountId: string, revealedEvents: TimelineEventItem[]): ElementDefinition[] {
  const counterparties = new Map<string, boolean>();
  for (const event of revealedEvents) {
    const flagged = counterparties.get(event.counterparty_account_id) ?? false;
    counterparties.set(event.counterparty_account_id, flagged || event.is_laundering);
  }

  const nodes: ElementDefinition[] = [
    { data: { id: accountId, label: truncate(accountId, 10), isCenter: true } },
    ...Array.from(counterparties.entries()).map(([id, everFlagged]) => ({
      data: { id, label: truncate(id, 10), isCenter: false, everFlagged },
    })),
  ];

  const maxAmount = revealedEvents.reduce((max, e) => Math.max(max, e.amount), 1);
  const edges: ElementDefinition[] = revealedEvents.map((event) => ({
    data: {
      id: event.txn_id,
      source: event.direction === "out" ? accountId : event.counterparty_account_id,
      target: event.direction === "out" ? event.counterparty_account_id : accountId,
      width: 1.5 + (Math.log10(event.amount + 1) / Math.log10(maxAmount + 1)) * 6,
      isLaundering: event.is_laundering,
    },
  }));

  return [...nodes, ...edges];
}

function buildStylesheet(theme: GraphTheme): StylesheetJsonBlock[] {
  const rules: Array<{ selector: string; style: Record<string, unknown> }> = [
    {
      selector: "node",
      style: {
        "background-color": theme.roleNormal,
        width: 32,
        height: 32,
        label: "data(label)",
        "font-size": 8,
        color: theme.label,
        "text-valign": "bottom",
        "text-margin-y": 4,
        "border-width": 1,
        "border-color": theme.edge,
      },
    },
    {
      selector: "node[?isCenter]",
      style: {
        "background-color": theme.centerFill,
        width: 44,
        height: 44,
        "border-width": 3,
        "border-color": theme.centerStroke,
      },
    },
    {
      selector: "node[?everFlagged]",
      style: {
        "border-width": 3,
        "border-color": theme.statusFlag,
      },
    },
    {
      selector: "edge",
      style: {
        width: "data(width)",
        "line-color": theme.edge,
        "target-arrow-color": theme.edge,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.7,
        "curve-style": "bezier",
        opacity: 0.85,
      },
    },
    {
      selector: "edge[?isLaundering]",
      style: {
        "line-style": "dashed",
        "line-color": theme.statusFlag,
        "target-arrow-color": theme.statusFlag,
      },
    },
  ];
  return rules as unknown as StylesheetJsonBlock[];
}

/**
 * L2 §8 — Graph Replay (ROADMAP Phase 18): an animated timeline scrubber
 * that progressively reveals transactions/edges in chronological order.
 * Pure frontend enrichment, no new backend call — reuses the exact same
 * `GET .../timeline` endpoint `investigation-timeline.tsx` already fetches
 * (own independent fetch though, not shared state, matching this app's
 * "every section owns its own fetch" convention), which is already
 * ascending-by-timestamp (`investigation/timeline.py`'s own docstring), so
 * no client-side re-sort is needed.
 *
 * Kept as its own component/section rather than retrofitted into
 * `InvestigationGraphSection` — that component already owns a complex
 * filter+selection state machine, and "what's currently revealed by replay
 * position" is a genuinely different, animation-driven state axis that
 * would otherwise get tangled with it (ROADMAP Phase 18 scope note).
 *
 * Mechanics (judgment call, since the roadmap leaves the exact
 * implementation open): an index into the sorted event list, advanced by a
 * `setInterval` while playing at `BASE_STEP_MS / speed` per step, one
 * event revealed per tick — simple and predictable rather than
 * time-proportional (i.e. NOT scaled to the real gap between two
 * transactions' timestamps, which for this dataset's dormancy/reactivation
 * patterns could mean waiting through a multi-month simulated gap or
 * flashing through a burst too fast to read either way). Scrubbing the
 * slider manually pauses playback (an explicit seek always wins over the
 * timer).
 */
export function GraphReplaySection({ caseId, accountId }: { caseId: string; accountId: string }) {
  const { data, loading, error } = useTriageFetch<TimelineResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/accounts/${encodeURIComponent(accountId)}/timeline`,
  );

  const events = useMemo(() => data?.events ?? [], [data]);
  const [revealedCount, setRevealedCount] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);

  // A fresh timeline (new account, or the same account's data reloading)
  // resets playback rather than leaving a stale scrub position pointed at
  // an index that may no longer mean the same thing. Adjusted during
  // render (React's own documented "resetting state when a prop changes"
  // pattern — https://react.dev/learn/you-might-not-need-an-effect) rather
  // than in an Effect, which `eslint-plugin-react-hooks`'s
  // `set-state-in-effect` rule flags for a direct, unconditional setState
  // call in an effect body — same rule `use-triage-fetch.ts`'s own
  // docstring already works around for its "derive at render time"
  // convention.
  const [lastData, setLastData] = useState(data);
  if (data !== lastData) {
    setLastData(data);
    setRevealedCount(0);
    setPlaying(false);
  }

  // The interval callback itself calls `setPlaying(false)` (inside the
  // `setInterval` callback, not directly in the effect body) once playback
  // reaches the end — `revealedCount` is deliberately NOT an effect
  // dependency (read via the functional `setRevealedCount` updater
  // instead), so this effect only re-subscribes when `playing`/`speed`/
  // `events.length` actually change, not on every single revealed step.
  useEffect(() => {
    if (!playing || events.length === 0) return;
    const id = setInterval(() => {
      setRevealedCount((n) => {
        const next = Math.min(n + 1, events.length);
        if (next >= events.length) setPlaying(false);
        return next;
      });
    }, BASE_STEP_MS / speed);
    return () => clearInterval(id);
  }, [playing, speed, events.length]);

  const theme = useMemo(() => readGraphTheme(), []);
  const revealedEvents = useMemo(() => events.slice(0, revealedCount), [events, revealedCount]);
  const elements = useMemo(() => buildElements(accountId, revealedEvents), [accountId, revealedEvents]);
  const stylesheet = useMemo(() => buildStylesheet(theme), [theme]);

  const cyInstanceRef = useRef<Core | null>(null);
  const handleCyInit = useCallback((cy: Core) => {
    cyInstanceRef.current = cy;
  }, []);

  useEffect(() => {
    const cy = cyInstanceRef.current;
    if (!cy) return;
    cy.layout({
      name: "concentric",
      concentric: (node: NodeSingular) => (node.data("isCenter") ? 2 : 1),
      levelWidth: () => 1,
      minNodeSpacing: 40,
      animate: true,
      animationDuration: 250,
      fit: true,
    }).run();
  }, [elements]);

  function handlePlayPause() {
    if (!playing && revealedCount >= events.length && events.length > 0) {
      setRevealedCount(0);
    }
    setPlaying((p) => !p);
  }

  const currentEvent = revealedEvents.at(-1) ?? null;

  return (
    <TriageSection
      title="Graph Replay"
      description="Scrub or play back this account's transaction history in chronological order — one revealed edge per transaction."
      loading={loading}
      error={error}
      isEmpty={!!data && events.length === 0}
      emptyText="No transactions recorded for this account to replay."
    >
      {events.length > 0 && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" size="icon-sm" onClick={handlePlayPause} title={playing ? "Pause" : "Play"}>
              {playing ? <Pause /> : <Play />}
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => {
                setRevealedCount(0);
                setPlaying(false);
              }}
              title="Reset"
            >
              <RotateCcw />
            </Button>

            <div className="flex flex-1 items-center gap-2">
              <Label className="text-muted-foreground text-xs font-normal">
                {revealedCount} / {events.length} transactions
              </Label>
              <Slider
                min={0}
                max={events.length}
                step={1}
                value={[revealedCount]}
                onValueChange={(value) => {
                  setPlaying(false);
                  setRevealedCount(Array.isArray(value) ? value[0] : value);
                }}
                className="flex-1"
              />
            </div>

            <div className="flex items-center gap-1.5">
              <Label className="text-muted-foreground text-xs font-normal">Speed</Label>
              <Select value={String(speed)} onValueChange={(value) => setSpeed(Number(value))}>
                <SelectTrigger size="sm" className="w-20">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SPEED_OPTIONS.map((s) => (
                    <SelectItem key={s} value={String(s)}>
                      {s}×
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <p className="text-muted-foreground text-xs">
            {currentEvent
              ? `Showing up to ${formatDateTime(currentEvent.timestamp)}.`
              : "Nothing revealed yet — press play or drag the scrubber."}
          </p>

          <CytoscapeComponent
            elements={elements}
            stylesheet={stylesheet}
            style={{ width: "100%", height: "360px" }}
            cy={handleCyInit}
            wheelSensitivity={0.2}
          />
        </div>
      )}
    </TriageSection>
  );
}
