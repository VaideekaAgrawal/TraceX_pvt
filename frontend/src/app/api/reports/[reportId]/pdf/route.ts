/**
 * BFF proxy for `GET /reports/{report_id}/pdf` (`backend/api/routes/
 * reports.py`) — streams the generated STR/SAR PDF bytes back to the
 * browser (ROADMAP Phase 21). This is this codebase's first BFF route
 * wrapping a binary (non-JSON) backend response — every other Route
 * Handler in this app assumes a JSON body on both success and error paths
 * (see `withBackendErrorMapping`'s docstring), which doesn't fit a
 * `FileResponse`. So this route talks to `reports-client.ts::
 * fetchReportPdf` directly rather than going through that shared helper,
 * and does its own success/error branching:
 *
 *   - `null` (no session cookie) -> 401 JSON, matching every other route's
 *     "not authenticated" shape.
 *   - non-2xx (404 "not generated yet", 403/404 case-access) -> the
 *     backend's JSON error body IS forwarded as JSON here (it really is
 *     JSON on this specific path — only the 200 response is binary).
 *   - 200 -> the PDF bytes are streamed straight through
 *     (`response.body`, a `ReadableStream`) with `Content-Type:
 *     application/pdf` and a `Content-Disposition: attachment` header, so
 *     a plain `<a href="/api/reports/{id}/pdf">` download link works
 *     natively — no client-side Blob juggling needed.
 */
import { NextResponse } from "next/server";

import { BackendApiError } from "@/lib/api/backend";
import { BackendUnavailableError } from "@/lib/api/auth-client";
import { fetchReportPdf } from "@/lib/api/reports-client";

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : `Request failed (${response.status})`;
  } catch {
    return `Request failed (${response.status})`;
  }
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await params;

  try {
    const response = await fetchReportPdf(reportId);
    if (response === null) {
      return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
    }
    if (!response.ok) {
      const detail = await readErrorDetail(response);
      return NextResponse.json({ detail }, { status: response.status });
    }
    return new NextResponse(response.body, {
      status: 200,
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${reportId}.pdf"`,
      },
    });
  } catch (err) {
    if (err instanceof BackendUnavailableError) {
      return NextResponse.json({ detail: err.message }, { status: 502 });
    }
    if (err instanceof BackendApiError) {
      return NextResponse.json({ detail: err.message }, { status: err.status });
    }
    throw err;
  }
}
