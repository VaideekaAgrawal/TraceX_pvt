"use client";

/**
 * Permanent top nav — the entire top-level chrome per FRONTEND_PLAN.md §1:
 * three page links, notification bell, user/role indicator. Nothing else.
 * No Graphs/Anomaly/Patterns-style top-level links — the three-page model
 * (Dashboard, Investigation Workspace, My Center) is deliberate, not a
 * placeholder to be added to later.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";
import { NotificationBell } from "@/components/shell/notification-bell";
import { UserMenu } from "@/components/shell/user-menu";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/workspace", label: "Investigation Workspace" },
  { href: "/my-center", label: "My Center" },
] as const;

export function TopNav() {
  const pathname = usePathname();

  return (
    <header className="border-b bg-background">
      <div className="flex h-14 items-center gap-6 px-4 sm:px-6">
        <span className="text-sm font-semibold tracking-tight">TraceX</span>

        <nav className="flex items-center gap-1">
          {NAV_ITEMS.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active
                    ? "bg-secondary text-secondary-foreground"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-1">
          <NotificationBell />
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
