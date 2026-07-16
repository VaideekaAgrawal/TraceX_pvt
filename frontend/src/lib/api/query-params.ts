/**
 * Shared query-string parsing for the two L2 transaction-search BFF routes
 * (`app/api/cases/[caseId]/transactions/search/route.ts` and its
 * account-scoped sibling under `accounts/[accountId]/transactions/search/`)
 * — both accept the exact same ~10-param filter set
 * (`api.routes.l2._TransactionSearchParams`), so this is factored out rather
 * than pasted twice. Same motivation `route-handler.ts`'s docstring gives
 * for its own extraction: duplicating a parsing block across two Route
 * Handlers is exactly the class of bug this codebase has already been
 * burned by once (see that file's docstring).
 */
import type { NextRequest } from "next/server";

import type { TransactionSearchParams } from "@/lib/api/types";

export function parseTransactionSearchParams(request: NextRequest): TransactionSearchParams {
  const searchParams = request.nextUrl.searchParams;
  const channels = searchParams.getAll("channels");

  return {
    min_amount: searchParams.get("min_amount") ? Number(searchParams.get("min_amount")) : undefined,
    max_amount: searchParams.get("max_amount") ? Number(searchParams.get("max_amount")) : undefined,
    start: searchParams.get("start") ?? undefined,
    end: searchParams.get("end") ?? undefined,
    channels: channels.length > 0 ? channels : undefined,
    direction: (searchParams.get("direction") as "in" | "out" | null) ?? undefined,
    txn_type: searchParams.get("txn_type") ?? undefined,
    limit: searchParams.get("limit") ? Number(searchParams.get("limit")) : undefined,
    offset: searchParams.get("offset") ? Number(searchParams.get("offset")) : undefined,
    sort: searchParams.get("sort") ?? undefined,
  };
}
