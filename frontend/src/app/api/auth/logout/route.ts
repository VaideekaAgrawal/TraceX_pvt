/**
 * Clears the session cookie. No backend call needed — the backend has no
 * token-revocation infrastructure (short-lived JWT, `foundation/auth.py`'s
 * own docstring notes `User.active` is the real revocation lever); logout
 * is purely "stop sending this cookie."
 */
import { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { SESSION_COOKIE_NAME } from "@/lib/auth/session";

export async function POST() {
  const cookieStore = await cookies();
  cookieStore.delete(SESSION_COOKIE_NAME);
  return NextResponse.json({ ok: true }, { status: 200 });
}
