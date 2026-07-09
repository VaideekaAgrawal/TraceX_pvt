"use client";
import { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-slate-700/50 bg-[#111827] p-5 ${className}`}>
      {children}
    </div>
  );
}

export function StatCard({
  label,
  value,
  sub,
  icon,
  color = "blue",
}: {
  label: ReactNode;
  value: string | number;
  sub?: string;
  icon?: string;
  color?: "blue" | "red" | "orange" | "green" | "purple" | "yellow";
}) {
  const colorMap = {
    blue: "from-blue-500/20 to-blue-600/5 border-blue-500/20",
    red: "from-red-500/20 to-red-600/5 border-red-500/20",
    orange: "from-orange-500/20 to-orange-600/5 border-orange-500/20",
    green: "from-green-500/20 to-green-600/5 border-green-500/20",
    purple: "from-purple-500/20 to-purple-600/5 border-purple-500/20",
    yellow: "from-yellow-500/20 to-yellow-600/5 border-yellow-500/20",
  };
  const textColor = {
    blue: "text-blue-400", red: "text-red-400", orange: "text-orange-400",
    green: "text-green-400", purple: "text-purple-400", yellow: "text-yellow-400",
  };

  return (
    <div className={`rounded-xl border bg-gradient-to-br p-5 ${colorMap[color]}`}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-slate-400 uppercase tracking-wider">{label}</p>
        {icon && <span className="text-lg">{icon}</span>}
      </div>
      <p className={`mt-2 text-2xl font-bold ${textColor[color]}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

export function Badge({ children, variant = "default" }: { children: ReactNode; variant?: "default" | "danger" | "warning" | "success" | "info" }) {
  const styles = {
    default: "bg-slate-700 text-slate-300",
    danger: "bg-red-500/20 text-red-400 border border-red-500/30",
    warning: "bg-orange-500/20 text-orange-400 border border-orange-500/30",
    success: "bg-green-500/20 text-green-400 border border-green-500/30",
    info: "bg-blue-500/20 text-blue-400 border border-blue-500/30",
  };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${styles[variant]}`}>
      {children}
    </span>
  );
}

export function Loader() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
    </div>
  );
}

export function EmptyState({ message = "No data available" }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-500">
      <span className="text-4xl mb-3">📭</span>
      <p className="text-sm">{message}</p>
    </div>
  );
}

// ── Skeleton Loader ─────────────────────────────────────────────────────────
export function SkeletonCard() {
  return (
    <div className="rounded-xl border border-slate-700/50 bg-[#111827] p-5 animate-pulse">
      <div className="h-3 w-24 bg-slate-700 rounded mb-3" />
      <div className="h-6 w-16 bg-slate-700 rounded mb-2" />
      <div className="h-2 w-32 bg-slate-800 rounded" />
    </div>
  );
}

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2 animate-pulse">
      <div className="h-8 bg-slate-800 rounded w-full" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-6 bg-slate-800/50 rounded w-full" />
      ))}
    </div>
  );
}

// ── Info Tooltip ────────────────────────────────────────────────────────────
export function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="relative group inline-flex items-center ml-1.5 cursor-help">
      <span className="text-slate-500 hover:text-slate-300 text-xs leading-none">ⓘ</span>
      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-2.5 rounded-lg bg-slate-800 border border-slate-600 text-xs text-slate-300 leading-relaxed shadow-xl opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
        {text}
      </span>
    </span>
  );
}

// ── Filter Bar ──────────────────────────────────────────────────────────────
export interface FilterOption {
  key: string;
  label: string;
  type: "select" | "text" | "number" | "date";
  options?: { value: string; label: string }[];
  placeholder?: string;
}

export function FilterBar({
  filters,
  values,
  onChange,
  onReset,
}: {
  filters: FilterOption[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  onReset: () => void;
}) {
  const hasActiveFilters = Object.values(values).some((v) => v !== "");
  return (
    <div className="flex flex-wrap items-center gap-2 p-3 rounded-lg bg-slate-900/50 border border-slate-700/50">
      <span className="text-xs text-slate-500 font-medium mr-1">🔍 Filters:</span>
      {filters.map((f) => (
        <div key={f.key} className="flex-shrink-0">
          {f.type === "select" ? (
            <select
              value={values[f.key] || ""}
              onChange={(e) => onChange(f.key, e.target.value)}
              className="text-xs rounded-md bg-slate-800 border border-slate-700 px-2 py-1.5 text-white focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="">{f.label}: All</option>
              {f.options?.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : f.type === "number" ? (
            <input
              type="number"
              value={values[f.key] || ""}
              onChange={(e) => onChange(f.key, e.target.value)}
              placeholder={f.placeholder || f.label}
              className="text-xs rounded-md bg-slate-800 border border-slate-700 px-2 py-1.5 text-white w-24 focus:ring-1 focus:ring-blue-500"
            />
          ) : f.type === "date" ? (
            <input
              type="date"
              value={values[f.key] || ""}
              onChange={(e) => onChange(f.key, e.target.value)}
              className="text-xs rounded-md bg-slate-800 border border-slate-700 px-2 py-1.5 text-white focus:ring-1 focus:ring-blue-500"
            />
          ) : (
            <input
              type="text"
              value={values[f.key] || ""}
              onChange={(e) => onChange(f.key, e.target.value)}
              placeholder={f.placeholder || f.label}
              className="text-xs rounded-md bg-slate-800 border border-slate-700 px-2 py-1.5 text-white w-28 focus:ring-1 focus:ring-blue-500"
            />
          )}
        </div>
      ))}
      {hasActiveFilters && (
        <button
          onClick={onReset}
          className="text-xs px-2 py-1 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30"
        >
          ✕ Clear
        </button>
      )}
    </div>
  );
}
