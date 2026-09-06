"""
Reset `data/tracex_demo_live.db` to the scripted-demo starting state.

The demo (`docs/DEMO_SCRIPT.md`) walks ONE case end to end and mutates it
(escalate -> close TP -> STR filed), so it is not re-runnable without a reset.
This script is that reset, and it is idempotent: run it before every rehearsal
and before the real thing.

What it does:
  1. Copies the committed pitch dataset (`data/tracex_demo.db`) over the
     gitignored throwaway (`data/tracex_demo_live.db`). The committed DB is
     never demoed against directly -- every click would dirty the shared
     dataset.
  2. Rewinds the hero case to "landed on my desk today":
       - status IN_PROGRESS -> ASSIGNED (the committed dataset has it already
         started, from an earlier rehearsal on 2026-08-19), so the investigator
         genuinely starts from the beginning on camera
       - drops the stale ASSIGNED->IN_PROGRESS `case_status_history` row
       - re-dates the case + its alert to today, so the queue reads as a fresh
         overnight detection run rather than a seven-week-old backlog item

Transaction timestamps are deliberately NOT shifted. The suspicious activity
stays in June; the alert lands today. That is how batch AML detection actually
works (60-90 day lookbacks are standard), and it avoids mutating 2,316
transaction rows plus every derived artifact for a purely cosmetic gain.

Usage (from backend/):
    .venv/bin/python scripts/prep_demo_live.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

#: The hero case `docs/DEMO_SCRIPT.md` is built around.
HERO_CASE = "CASE-20260718-13F5F994"

REPO = Path(__file__).resolve().parents[2]
COMMITTED = REPO / "data" / "tracex_demo.db"
LIVE = REPO / "data" / "tracex_demo_live.db"


def main() -> int:
    if not COMMITTED.exists():
        print(f"error: committed demo DB missing at {COMMITTED}", file=sys.stderr)
        return 1

    shutil.copyfile(COMMITTED, LIVE)
    print(f"reset  {LIVE.name} <- {COMMITTED.name}")

    # "Today", with the alert fired overnight and the SLA clock already running.
    # Written as strings in the exact format SQLAlchemy already stores, rather
    # than as `datetime` objects -- sqlite3's implicit datetime adapter is
    # deprecated as of Python 3.12 and warns on every run otherwise.
    fmt = "%Y-%m-%d %H:%M:%S.%f"
    now = datetime.now()
    _assigned = now.replace(hour=8, minute=30, second=0, microsecond=0)
    detected_at = now.replace(hour=2, minute=14, second=0, microsecond=0).strftime(fmt)
    assigned_at = _assigned.strftime(fmt)
    sla_due_at = (_assigned + timedelta(hours=24)).strftime(fmt)

    con = sqlite3.connect(LIVE)
    try:
        row = con.execute(
            "select status, level from cases where case_id = ?", (HERO_CASE,)
        ).fetchone()
        if row is None:
            print(f"error: hero case {HERO_CASE} not found", file=sys.stderr)
            return 1
        print(f"hero   {HERO_CASE}: was status={row[0]} level={row[1]}")

        con.execute(
            """update cases
                  set status = 'ASSIGNED',
                      level = 'L1',
                      resolution = NULL,
                      resolution_reason = NULL,
                      closed_at = NULL,
                      evidence_hash = NULL,
                      created_at = ?,
                      updated_at = ?,
                      sla_due_at = ?
                where case_id = ?""",
            (detected_at, assigned_at, sla_due_at, HERO_CASE),
        )

        # Drop every transition after the original auto-assignment, so the
        # case history reads as "assigned this morning, untouched since".
        con.execute(
            "delete from case_status_history where case_id = ? and to_status != 'ASSIGNED'",
            (HERO_CASE,),
        )
        con.execute(
            """update case_status_history
                  set changed_at = ?
                where case_id = ? and to_status = 'ASSIGNED'""",
            (assigned_at, HERO_CASE),
        )

        con.execute(
            """update alerts
                  set status = 'assigned',
                      created_at = ?,
                      last_seen_at = ?
                where case_id = ?""",
            (detected_at, detected_at, HERO_CASE),
        )

        # A case walked in a previous rehearsal leaves these behind.
        con.execute("delete from reports where case_id = ?", (HERO_CASE,))
        con.execute("delete from ai_interactions where case_id = ?", (HERO_CASE,))
        con.execute("delete from notes where case_id = ?", (HERO_CASE,))

        con.commit()

        status, level, created, sla = con.execute(
            "select status, level, created_at, sla_due_at from cases where case_id = ?",
            (HERO_CASE,),
        ).fetchone()
        print(f"hero   {HERO_CASE}: now status={status} level={level}")
        print(f"       detected {created}  |  SLA due {sla}")
    finally:
        con.close()

    print("\nready. start the stack:")
    print("  cd backend && .venv/bin/uvicorn api.app:create_app --factory --port 8001")
    print("  cd frontend && npm run dev")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
