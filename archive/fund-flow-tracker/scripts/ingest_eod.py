#!/usr/bin/env python3
"""
CLI script for EOD ingestion — designed for cron / Cloud Scheduler.

Usage:
    python scripts/ingest_eod.py --filepath data/daily_txns.csv --date 2026-05-31
    python scripts/ingest_eod.py --filepath data/daily_txns.csv  # auto-detect date

Environment:
    DB_BACKEND=neo4j|sqlite   (default: sqlite)
    NEO4J_URI=neo4j+s://...   (for neo4j backend)
    NEO4J_USER=neo4j
    NEO4J_PASSWORD=...
    SQLITE_PATH=data/tracex.db
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ingestion.eod_service import EODIngestionService


def main():
    parser = argparse.ArgumentParser(description="TraceX EOD Ingestion CLI")
    parser.add_argument("--filepath", "-f", required=True, help="Path to daily transaction CSV")
    parser.add_argument("--date", "-d", default=None, help="Ingestion date (YYYY-MM-DD)")
    parser.add_argument("--max-rows", "-n", type=int, default=None, help="Limit rows (for testing)")
    parser.add_argument("--force", action="store_true", help="Force re-ingestion even if file was already processed")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")

    args = parser.parse_args()

    if not os.path.exists(args.filepath):
        print(f"ERROR: File not found: {args.filepath}", file=sys.stderr)
        sys.exit(1)

    svc = EODIngestionService()

    try:
        result = svc.ingest_daily_file(
            filepath=args.filepath,
            date=args.date,
            max_rows=args.max_rows,
            force=args.force,
        )

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result["status"] == "skipped":
                print(f"⏭️  Skipped (already ingested): {result.get('file_hash', '')}")
            else:
                print(f"✅ Ingestion complete:")
                print(f"   Date: {result['date']}")
                print(f"   Transactions: {result['total_transactions']}")
                print(f"   Accounts: {result['total_accounts']} ({result['new_accounts']} new)")
                print(f"   Alerts: {result['alerts_generated']}")
                print(f"   Patterns: {result.get('patterns_detected', {})}")
                print(f"   Time: {result['processing_time_sec']}s")

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
