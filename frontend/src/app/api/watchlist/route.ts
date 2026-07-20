/**
 * BFF proxy for `GET/POST /watchlist` (`backend/api/routes/watchlist.py`)
 * — My Center → Monitoring (ROADMAP Phase 21). `GET` is open to any
 * authenticated user server-side; `POST` is Admin/Compliance only (403
 * otherwise) — `monitoring-section.tsx` hides the add form for a
 * non-admin, this route just forwards the real 403 if it's ever hit
 * anyway. Mirrors `app/api/audit-log/route.ts`'s structure (this
 * codebase's closest existing list+add BFF template).
 */
import { NextResponse } from "next/server";

import { addWatchlistEntry, listWatchlist } from "@/lib/api/watchlist-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { AddWatchlistRequest } from "@/lib/api/types";

export async function GET() {
  return withBackendErrorMapping(async () => {
    const result = await listWatchlist();
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}

export async function POST(request: Request) {
  let body: AddWatchlistRequest;
  try {
    body = (await request.json()) as AddWatchlistRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.entity_type || !body.entity_value || !body.entity_value.trim()) {
    return NextResponse.json(
      { detail: "entity_type and entity_value are required" },
      { status: 400 },
    );
  }

  return withBackendErrorMapping(async () => {
    const result = await addWatchlistEntry(body);
    return NextResponse.json(result, { status: 201 });
  });
}
