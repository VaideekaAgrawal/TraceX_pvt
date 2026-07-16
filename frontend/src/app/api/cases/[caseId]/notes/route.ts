/**
 * BFF proxy for `GET/POST /cases/{case_id}/notes` (`backend/api/routes/
 * l2.py`) — L1 Triage's Investigator Notes section (debounced autosave, no
 * manual "Save" button — see `components/workspace/triage/notes-panel.tsx`).
 */
import { NextResponse } from "next/server";

import { createNote, listNotes } from "@/lib/api/case-detail-client";
import { withBackendErrorMapping } from "@/lib/api/route-handler";
import type { NoteCreateRequest } from "@/lib/api/types";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  return withBackendErrorMapping(async () => {
    const result = await listNotes(caseId);
    if (result === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    return NextResponse.json(result, { status: 200 });
  });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ caseId: string }> },
) {
  const { caseId } = await params;

  let body: NoteCreateRequest;
  try {
    body = (await request.json()) as NoteCreateRequest;
  } catch {
    return NextResponse.json({ detail: "Malformed request body" }, { status: 400 });
  }

  if (!body.body || !body.body.trim()) {
    return NextResponse.json({ detail: "body is required" }, { status: 400 });
  }

  return withBackendErrorMapping(async () => {
    const result = await createNote(caseId, body);
    return NextResponse.json(result, { status: 201 });
  });
}
