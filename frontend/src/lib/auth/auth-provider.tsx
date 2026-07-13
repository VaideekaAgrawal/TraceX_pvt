"use client";

/**
 * Top-level auth context. Seeded once from the server (root layout calls
 * `GET /auth/me` and passes the resolved user in) — this provider never
 * fetches on its own; it just holds that value and exposes `logout()`.
 *
 * Not Zustand deliberately: Zustand is reserved for per-case-tab state
 * starting Phase 15 (FRONTEND_ROADMAP.md decision 2). Auth is a single
 * global value with no per-case keying, so plain React Context is the
 * right-sized tool here.
 */
import { createContext, useCallback, useContext, useMemo } from "react";

import type { CurrentUser, UserRole } from "@/lib/api/types";

interface AuthContextValue {
  user: CurrentUser | null;
  isAuthenticated: boolean;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({
  user,
  children,
}: {
  user: CurrentUser | null;
  children: React.ReactNode;
}) {
  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    // Full navigation (not router.push) so every client-held auth state
    // resets cleanly and the root layout re-derives from cookies again.
    window.location.assign("/login");
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, isAuthenticated: user !== null, logout }),
    [user, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

/**
 * Convenience hook for role-conditional rendering, ready for later phases
 * (Phase 14+) to consume — e.g. `useRole() === "ADMIN_COMPLIANCE"` to show
 * an assign control. Per FRONTEND_ROADMAP.md decision 6: this is always a
 * UX courtesy, never the actual permission gate — the backend enforces
 * RBAC independently and wins on any disagreement.
 */
export function useRole(): UserRole | null {
  const { user } = useAuth();
  return user?.role ?? null;
}
