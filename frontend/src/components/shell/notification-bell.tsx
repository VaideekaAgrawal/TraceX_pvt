"use client";

/**
 * Fetches the curated audit-log feed on mount (ROADMAP Phase 14),
 * replacing Phase 13's static "not wired up yet" placeholder. Curated via
 * a fixed `action` allowlist (`case_assigned`, `case_reassigned`,
 * `escalated`, `decision_changed`) rather than the full audit trail — this
 * is a notification feed, not a general-purpose log viewer.
 *
 * Badge count is the query's real `total_count` (how many matching
 * entries exist, not just how many were fetched into the dropdown) —
 * never a fabricated number, matching the "no fake unread count"
 * invariant this component's Phase 13 docstring already called out. There
 * is no read/unread tracking in this phase; it's a real total, not an
 * unread total.
 */
import { useEffect, useState } from "react";
import { Bell } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { AuditLogItem, AuditLogListResponse } from "@/lib/api/types";

const CURATED_ACTIONS = ["case_assigned", "case_reassigned", "escalated", "decision_changed"];

const ACTION_LABELS: Record<string, string> = {
  case_assigned: "Case assigned",
  case_reassigned: "Case reassigned",
  escalated: "Case escalated",
  decision_changed: "Case decision recorded",
};

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action;
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function NotificationBell() {
  const [items, setItems] = useState<AuditLogItem[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const qs = new URLSearchParams();
    for (const action of CURATED_ACTIONS) qs.append("action", action);
    qs.set("limit", "10");

    fetch(`/api/audit-log?${qs.toString()}`, { cache: "no-store" })
      .then((res) => (res.ok ? (res.json() as Promise<AuditLogListResponse>) : null))
      .then((body) => {
        if (cancelled || !body) return;
        setItems(body.items);
        setTotalCount(body.total_count);
      })
      .catch(() => {
        // Non-fatal — the bell just shows an empty state rather than
        // crashing the shell.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" aria-label="Notifications" className="relative">
            <Bell className="size-5" />
            {totalCount > 0 && (
              <Badge
                variant="destructive"
                className="absolute -top-1 -right-1 h-4 min-w-4 justify-center rounded-full px-1 text-[10px]"
              >
                {totalCount > 99 ? "99+" : totalCount}
              </Badge>
            )}
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Recent activity</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {loading ? (
          <DropdownMenuItem disabled className="text-muted-foreground text-sm">
            Loading…
          </DropdownMenuItem>
        ) : items.length === 0 ? (
          <DropdownMenuItem disabled className="text-muted-foreground text-sm">
            No recent activity.
          </DropdownMenuItem>
        ) : (
          items.map((item) => (
            <DropdownMenuItem key={item.id} disabled className="flex-col items-start gap-0.5">
              <span className="text-sm font-medium">{actionLabel(item.action)}</span>
              <span className="text-muted-foreground text-xs">
                {item.case_id ? `Case ${item.case_id} · ` : ""}
                {formatTimestamp(item.created_at)}
              </span>
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
