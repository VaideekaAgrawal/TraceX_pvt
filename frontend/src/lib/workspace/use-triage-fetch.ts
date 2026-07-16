"use client";

/**
 * Shared "fetch this L1 Triage section's data once when the tab opens"
 * hook, used by every section component under `components/workspace/
 * triage/`. Each section fetches independently (one endpoint failing
 * doesn't block the other nine) rather than one aggregate fetch — matches
 * this phase's per-section-endpoint shape.
 *
 * Stale-response guard via a `latestRequestId` ref, same pattern
 * `case-queue.tsx`'s `fetchCases` already established (and the same class
 * of bug Phase 15's code review caught there — an in-flight request from a
 * previous `url` must not overwrite a newer one's result). Fetches exactly
 * once per distinct `url` (not on every render) via the effect's own
 * dependency array.
 */
import { useCallback, useEffect, useRef, useState } from "react";

interface TriageFetchState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useTriageFetch<T>(url: string | null): TriageFetchState<T> {
  const [data, setData] = useState<T | null>(null);
  // Internal flag only — the returned `loading` below is derived from this
  // AND `url` at render time, rather than the effect synchronously
  // setState-ing a `false` value the instant `url` is `null` (a pattern
  // `eslint-plugin-react-hooks`'s `set-state-in-effect` rule flags: that
  // value is already fully derivable from `url` without an effect at all).
  const [inFlight, setInFlight] = useState(url !== null);
  const [error, setError] = useState<string | null>(null);
  const latestRequestId = useRef(0);
  // Bumped by `refetch()` to force the effect below to re-run even though
  // `url` itself hasn't changed.
  const [refetchNonce, setRefetchNonce] = useState(0);

  useEffect(() => {
    if (url === null) return;
    const requestId = ++latestRequestId.current;
    void (async () => {
      setInFlight(true);
      setError(null);
      try {
        const res = await fetch(url, { cache: "no-store" });
        const body = await res.json();
        if (!res.ok) {
          throw new Error(typeof body.detail === "string" ? body.detail : "Request failed");
        }
        if (requestId === latestRequestId.current) {
          setData(body as T);
        }
      } catch (err) {
        if (requestId === latestRequestId.current) {
          setError(err instanceof Error ? err.message : "Request failed");
        }
      } finally {
        if (requestId === latestRequestId.current) {
          setInFlight(false);
        }
      }
    })();
  }, [url, refetchNonce]);

  const refetch = useCallback(() => setRefetchNonce((n) => n + 1), []);

  return { data, loading: url !== null && inFlight, error, refetch };
}
