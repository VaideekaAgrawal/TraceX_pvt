"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Dashboard", icon: "📊" },
  { href: "/ingest", label: "Ingest Data", icon: "📥" },
  { href: "/graph", label: "Graph Explorer", icon: "🔍" },
  { href: "/anomaly", label: "Anomaly Detection", icon: "⚠️" },
  { href: "/rl-queue", label: "RL Adaptive Queue", icon: "🤖" },
  { href: "/patterns", label: "Pattern Detector", icon: "🔄" },
  { href: "/rules", label: "Rule Engine", icon: "⚙️" },
  { href: "/profile", label: "Profile Analyzer", icon: "👤" },
  { href: "/channels", label: "Channel Analytics", icon: "📡" },
  { href: "/evidence", label: "FIU Evidence", icon: "📋" },
  { href: "/realtime", label: "Real-Time Detection", icon: "⚡" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <header className="fixed top-0 left-0 right-0 z-40 border-b border-slate-700/50 bg-[#0f172a]/95 backdrop-blur-md">
      <div className="flex items-center h-14 px-6 gap-6">
        {/* Brand */}
        <Link href="/" className="flex items-center gap-2.5 shrink-0">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-xs font-bold text-white">
            TX
          </div>
          <div className="hidden sm:block">
            <h1 className="text-sm font-bold text-white tracking-tight leading-none">TraceX</h1>
            <p className="text-[9px] text-slate-500 uppercase tracking-widest">AML Intelligence</p>
          </div>
        </Link>

        {/* Divider */}
        <div className="h-6 w-px bg-slate-700/50" />

        {/* Navigation */}
        <nav className="flex items-center gap-1 overflow-x-auto flex-1">
          {navItems.map((item) => {
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium whitespace-nowrap transition-all duration-150",
                  isActive
                    ? "bg-blue-600/20 text-blue-400 border border-blue-500/30"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200 border border-transparent"
                )}
              >
                <span className="text-sm">{item.icon}</span>
                <span className="hidden md:inline">{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {/* Status */}
        <div className="flex items-center gap-2 shrink-0">
          <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-[10px] text-slate-500 hidden lg:inline">Union Bank • AML</span>
        </div>
      </div>
    </header>
  );
}
