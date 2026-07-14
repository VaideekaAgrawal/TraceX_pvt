"use client";

/**
 * Static shell only — Phase 13 scope explicitly excludes notification
 * content (that's Phase 14, backed by a curated `GET /audit-log` feed).
 * Renders the bell + a disabled-looking badge/dropdown affordance so the
 * chrome is in place without pretending there's real data behind it yet
 * (no fake unread count — the cross-phase invariant against presenting
 * mocked data as real applies here too).
 */
import { Bell } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";

export function NotificationBell() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" aria-label="Notifications">
            <Bell className="size-5" />
          </Button>
        }
      />
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuItem disabled className="text-muted-foreground text-sm">
          Notifications are not wired up yet.
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
