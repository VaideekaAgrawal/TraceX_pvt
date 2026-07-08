export function formatINR(amount: number | null | undefined): string {
  if (amount == null || isNaN(amount)) return "₹0";
  if (amount >= 1e7) return `₹${(amount / 1e7).toFixed(2)} Cr`;
  if (amount >= 1e5) return `₹${(amount / 1e5).toFixed(2)} L`;
  if (amount >= 1e3) return `₹${(amount / 1e3).toFixed(1)} K`;
  return `₹${amount.toFixed(0)}`;
}

export function getRiskBg(level: string): string {
  switch (level) {
    case "CRITICAL": return "bg-red-500/20 text-red-400 border-red-500/30";
    case "HIGH": return "bg-orange-500/20 text-orange-400 border-orange-500/30";
    case "MEDIUM": return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
    case "LOW": return "bg-green-500/20 text-green-400 border-green-500/30";
    default: return "bg-slate-500/20 text-slate-400 border-slate-500/30";
  }
}

export function getRiskDot(level: string): string {
  switch (level) {
    case "CRITICAL": return "bg-red-500";
    case "HIGH": return "bg-orange-500";
    case "MEDIUM": return "bg-yellow-500";
    case "LOW": return "bg-green-500";
    default: return "bg-slate-500";
  }
}

export function getPriorityColor(priority: string): string {
  switch (priority) {
    case "P1": return "bg-red-500 text-white";
    case "P2": return "bg-orange-500 text-white";
    case "P3": return "bg-yellow-500 text-black";
    case "P4": return "bg-slate-500 text-white";
    default: return "bg-slate-700 text-slate-300";
  }
}

export function getRoleIcon(role: string): string {
  switch (role) {
    case "SOURCE": return "🔴";
    case "MULE": return "🟡";
    case "SINK": return "🟢";
    case "NORMAL": return "⚪";
    default: return "❓";
  }
}

export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}
