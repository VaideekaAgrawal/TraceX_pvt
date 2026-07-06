"""
Database adapter — Neo4j (preferred) with SQLite fallback.

Provides a unified interface for storing and querying:
- Accounts (nodes)
- Transactions (edges/relationships)
- Alerts and detections
- Ingestion metadata (idempotency)

Configuration via environment variables:
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD  — for Neo4j Aura free tier
  DB_BACKEND=neo4j|sqlite                 — select backend (default: sqlite)
  SQLITE_PATH=data/tracex.db             — path for SQLite fallback
"""
import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────

DB_BACKEND = os.getenv("DB_BACKEND", "sqlite")
NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_SQLITE_PATH = os.path.abspath(os.path.join(_THIS_DIR, "..", "data", "tracex.db"))
SQLITE_PATH = os.getenv("SQLITE_PATH", _DEFAULT_SQLITE_PATH)


# ─── Abstract interface ───────────────────────────────────────────────────

class DatabaseAdapter:
    """Abstract DB interface for TraceX."""

    def initialize(self):
        """Create schema/indexes."""
        raise NotImplementedError

    def close(self):
        """Close connections."""
        pass

    # ── Accounts ──
    def upsert_accounts(self, accounts: List[Dict]) -> int:
        raise NotImplementedError

    def get_account(self, account_id: str) -> Optional[Dict]:
        raise NotImplementedError

    def account_exists(self, account_id: str) -> bool:
        raise NotImplementedError

    # ── Transactions ──
    def insert_transactions(self, transactions: List[Dict]) -> int:
        raise NotImplementedError

    def get_transactions_for_account(self, account_id: str, days: int = 7) -> List[Dict]:
        raise NotImplementedError

    def get_transactions_between(self, start: str, end: str, limit: int = 10000) -> List[Dict]:
        raise NotImplementedError

    # ── Alerts ──
    def upsert_alert(self, alert: Dict) -> None:
        raise NotImplementedError

    def get_alerts(self, status: Optional[str] = None, risk_level: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> List[Dict]:
        raise NotImplementedError

    def get_alert(self, alert_id: str) -> Optional[Dict]:
        raise NotImplementedError

    def close_stale_alerts(self, active_ids: List[str]) -> List[str]:
        raise NotImplementedError

    # ── Ingestion metadata ──
    def record_ingestion(self, file_hash: str, filename: str, date: str,
                         num_transactions: int, num_accounts: int) -> None:
        raise NotImplementedError

    def is_file_ingested(self, file_hash: str) -> bool:
        raise NotImplementedError

    def get_ingestion_history(self, limit: int = 50) -> List[Dict]:
        raise NotImplementedError

    # ── Graph queries ──
    def get_ego_graph(self, account_id: str, radius: int = 2) -> Dict:
        raise NotImplementedError

    def get_graph_filtered(self, risk_min: float = 0, risk_max: float = 100,
                           pattern: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           max_nodes: int = 100) -> Dict:
        raise NotImplementedError

    # ── Maintenance ──
    def delete_by_account_prefix(self, prefix: str) -> Dict[str, int]:
        """Delete all transactions/accounts/alerts whose account_id (or
        source/dest_account) starts with `prefix`. Used by the real-time demo to
        reset its own RTD-prefixed data at the start of each run, so repeated
        runs are deterministic instead of accumulating cross-run state."""
        raise NotImplementedError

    # ── Cases ──
    def create_case(self, case_data: Dict) -> Dict:
        raise NotImplementedError

    def get_cases(self) -> List[Dict]:
        raise NotImplementedError

    def get_case(self, case_id: str) -> Optional[Dict]:
        raise NotImplementedError

    def update_case_status(self, case_id: str, status: str, notes: str) -> Optional[Dict]:
        raise NotImplementedError

    # ── Daily run summary ──
    def record_daily_run_summary(self, summary: Dict) -> None:
        raise NotImplementedError

    def get_daily_run_summary(self, run_date: Optional[str] = None) -> Optional[Dict]:
        raise NotImplementedError

    def get_recent_run_summaries(self, limit: int = 14) -> List[Dict]:
        raise NotImplementedError

    # ── Detection rules ──
    def list_rules(self, enabled_only: bool = False) -> List[Dict]:
        raise NotImplementedError

    def get_rule(self, rule_id: str) -> Optional[Dict]:
        raise NotImplementedError

    def create_rule(self, rule: Dict) -> Dict:
        raise NotImplementedError

    def update_rule(self, rule_id: str, updates: Dict) -> Optional[Dict]:
        raise NotImplementedError

    def delete_rule(self, rule_id: str) -> bool:
        raise NotImplementedError

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> Optional[Dict]:
        raise NotImplementedError


# ─── SQLite Implementation ────────────────────────────────────────────────

class SQLiteAdapter(DatabaseAdapter):
    """SQLite fallback — good for local dev and small deployments."""

    def __init__(self, db_path: str = SQLITE_PATH):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    account_type TEXT,
                    branch_city TEXT,
                    occupation TEXT,
                    income_bracket TEXT,
                    declared_annual_income REAL DEFAULT 0,
                    risk_score REAL DEFAULT 0,
                    risk_level TEXT DEFAULT 'LOW',
                    role TEXT DEFAULT 'NORMAL',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    txn_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    source_account TEXT NOT NULL,
                    dest_account TEXT NOT NULL,
                    amount REAL NOT NULL,
                    channel TEXT DEFAULT 'unknown',
                    txn_type TEXT DEFAULT 'transfer',
                    is_laundering INTEGER DEFAULT 0,
                    ingestion_date TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    risk_score REAL DEFAULT 0,
                    risk_level TEXT DEFAULT 'LOW',
                    pattern_type TEXT,
                    status TEXT DEFAULT 'open',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    account_ids TEXT DEFAULT '[]',
                    detected_at TEXT,
                    last_seen_at TEXT,
                    severity TEXT DEFAULT 'MEDIUM',
                    details_json TEXT DEFAULT '',
                    source TEXT DEFAULT 'pipeline',
                    assigned_to TEXT DEFAULT '',
                    notes TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS ingestion_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_hash TEXT UNIQUE NOT NULL,
                    filename TEXT NOT NULL,
                    ingestion_date TEXT NOT NULL,
                    num_transactions INTEGER DEFAULT 0,
                    num_accounts INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'completed',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_txn_source ON transactions(source_account);
                CREATE INDEX IF NOT EXISTS idx_txn_dest ON transactions(dest_account);
                CREATE INDEX IF NOT EXISTS idx_txn_timestamp ON transactions(timestamp);
                CREATE INDEX IF NOT EXISTS idx_txn_ingestion_date ON transactions(ingestion_date);
                CREATE INDEX IF NOT EXISTS idx_alerts_account ON alerts(account_id);
                CREATE INDEX IF NOT EXISTS idx_alerts_risk_level ON alerts(risk_level);
                CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);
                CREATE INDEX IF NOT EXISTS idx_accounts_risk ON accounts(risk_score);
                CREATE INDEX IF NOT EXISTS idx_accounts_risk_level ON accounts(risk_level);

                CREATE TABLE IF NOT EXISTS cases (
                    case_id TEXT PRIMARY KEY,
                    account_ids TEXT NOT NULL,
                    risk_scores TEXT NOT NULL,
                    pattern_type TEXT NOT NULL,
                    notes TEXT DEFAULT '',
                    investigator TEXT DEFAULT 'Unassigned',
                    status TEXT DEFAULT 'open',
                    graph_snapshot TEXT DEFAULT '',
                    str_reference TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
                CREATE INDEX IF NOT EXISTS idx_cases_created_at ON cases(created_at);

                CREATE TABLE IF NOT EXISTS daily_run_summary (
                    run_date TEXT PRIMARY KEY,
                    run_at TEXT NOT NULL,
                    new_alert_ids TEXT NOT NULL,
                    reactivated_alert_ids TEXT NOT NULL,
                    stale_alert_ids TEXT NOT NULL,
                    total_accounts_flagged INTEGER DEFAULT 0,
                    total_alerts_open INTEGER DEFAULT 0,
                    accounts_ingested INTEGER DEFAULT 0,
                    transactions_ingested INTEGER DEFAULT 0,
                    pipeline_summary_json TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS detection_rules (
                    rule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    detection_type TEXT NOT NULL,
                    severity TEXT DEFAULT 'MEDIUM',
                    rule_json TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    is_builtin INTEGER DEFAULT 0,
                    version INTEGER DEFAULT 1,
                    created_by TEXT DEFAULT 'system',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS detection_rule_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    rule_json TEXT NOT NULL,
                    changed_by TEXT DEFAULT '',
                    changed_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_rules_enabled ON detection_rules(enabled);
                CREATE INDEX IF NOT EXISTS idx_rule_history_rule_id ON detection_rule_history(rule_id);
            """)
            conn.commit()
            self._migrate_alerts_table(conn)
            self._seed_builtin_rules_if_missing(conn)
        logger.info("SQLite database initialized at %s", self.db_path)

    def _seed_builtin_rules_if_missing(self, conn):
        """One-time, idempotent seed of the built-in detection rules — one
        per existing detector sub-check, with rule_json params equal to
        today's exact config defaults (or, for thresholds that were
        previously hardcoded literals rather than config fields, today's
        exact literal value). Behavior is byte-identical to the pre-Rule-
        Engine hardcoded detectors until someone edits a rule. Uses
        INSERT OR IGNORE on rule_id so re-running is always safe."""
        from infrastructure.config import config as _cfg
        import json as _json

        d = _cfg.detection
        builtin = [
            ("builtin_round_trip", "Round-Trip Circular Flow", "round_trip", "HIGH",
             "cycle", {"max_length": d.round_trip_max_cycle_length, "max_cycles": d.round_trip_max_cycles,
                       "min_return_ratio": d.round_trip_amount_return_ratio}),
            ("builtin_layering", "Multi-Hop Layering Chain", "layering", "HIGH",
             "chain", {"min_hops": d.layering_min_hops, "time_window_minutes": d.layering_time_window_minutes,
                       "extended_min_hops": d.layering_extended_min_hops,
                       "extended_window_minutes": d.layering_extended_window_minutes,
                       "decay_ratio_threshold": 0.5}),
            ("builtin_structuring_classic", "Structuring — Near-Threshold Amounts", "structuring", "HIGH",
             "amount_band_count", {"lower": d.structuring_lower, "upper": d.ctr_threshold,
                                    "min_count": d.structuring_min_count, "window_days": 30}),
            ("builtin_structuring_split", "Structuring — Split Daily Total", "structuring", "HIGH",
             "split_sum_threshold", {"lower": d.structuring_lower, "upper": d.ctr_threshold, "min_count": 2}),
            ("builtin_dormancy", "Dormant Account Reactivation", "dormancy", "MEDIUM",
             "inactivity_then_burst", {"threshold_days": d.dormancy_threshold_days,
                                       "min_burst_txns": d.dormancy_burst_min_txns,
                                       "multiplier": d.dormancy_multiplier}),
            ("builtin_fan_out", "Fan-Out Dispersal", "fan_out", "MEDIUM",
             "fan_degree", {"direction": "fan_out", "min_degree": d.fan_out_min_degree,
                            "window_days": d.fan_out_time_window_days}),
            ("builtin_fan_in", "Fan-In Consolidation", "fan_in", "MEDIUM",
             "fan_degree", {"direction": "fan_in", "min_degree": d.fan_out_min_degree,
                            "window_days": d.fan_out_time_window_days}),
            ("builtin_bipartite", "Bipartite Scatter-Gather", "fan_out", "MEDIUM",
             "bipartite_scatter_gather", {"min_side": 3, "window_days": d.fan_out_time_window_days}),
            ("builtin_income_mismatch", "Income vs. Volume Mismatch", "profile_mismatch", "MEDIUM",
             "volume_vs_declared_income_ratio", {"ratio_threshold": 10}),
            ("builtin_peer_deviation", "Peer Group Volume Deviation", "profile_mismatch", "MEDIUM",
             "peer_zscore_deviation", {"z_threshold": d.profile_mismatch_z_threshold, "min_peer_group_size": 5}),
            ("builtin_behavioural_shift", "Sudden Behavioural Shift", "profile_mismatch", "MEDIUM",
             "behavioural_shift", {"shift_z_threshold": 3, "min_txn_count": 15, "rolling_window": 20}),
        ]

        for rule_id, name, det_type, severity, primitive, params in builtin:
            rule_json = _json.dumps({
                "combinator": "AND",
                "conditions": [{"primitive": primitive, "params": params, "negate": False}],
            })
            conn.execute("""
                INSERT OR IGNORE INTO detection_rules
                    (rule_id, name, description, detection_type, severity, rule_json,
                     enabled, is_builtin, version, created_by)
                VALUES (?, ?, ?, ?, ?, ?, 1, 1, 1, 'system')
            """, (rule_id, name, f"Built-in rule mirroring the original {det_type} detector.",
                  det_type, severity, rule_json))
        conn.commit()

    def _migrate_alerts_table(self, conn):
        """Additive-only migration for DBs created before the unified alert
        store (Phase 2): adds the columns needed to make SQLite the single
        source of truth for alerts, without ever dropping/recreating the
        table (safe to run against an already-populated tracex.db)."""
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
        is_first_migration = "account_ids" not in existing_cols
        new_columns = {
            "account_ids": "TEXT DEFAULT '[]'",
            "detected_at": "TEXT",
            "last_seen_at": "TEXT",
            "severity": "TEXT DEFAULT 'MEDIUM'",
            "details_json": "TEXT DEFAULT ''",
            "source": "TEXT DEFAULT 'pipeline'",
            "assigned_to": "TEXT DEFAULT ''",
            "notes": "TEXT DEFAULT ''",
        }
        for col, ddl in new_columns.items():
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} {ddl}")
        conn.commit()

        if is_first_migration:
            # Backfill legacy rows so they don't silently lose their account
            # linkage/creation time — ALTER TABLE ADD COLUMN only applies the
            # DEFAULT going forward, existing rows would otherwise end up
            # with account_ids='[]' and detected_at=NULL despite having a
            # perfectly good account_id/created_at already on the row.
            rows = conn.execute(
                "SELECT alert_id, account_id, created_at FROM alerts WHERE account_ids = '[]' OR account_ids IS NULL"
            ).fetchall()
            for row in rows:
                if not row["account_id"]:
                    continue
                conn.execute(
                    "UPDATE alerts SET account_ids = ?, detected_at = ?, last_seen_at = ? WHERE alert_id = ?",
                    (json.dumps([row["account_id"]]), row["created_at"], row["created_at"], row["alert_id"]),
                )
            conn.commit()

    def close(self):
        pass  # connections are created and closed per-request in _get_conn

    # ── Accounts ──
    def upsert_accounts(self, accounts: List[Dict]) -> int:
        if not accounts:
            return 0
        with self._get_conn() as conn:
            inserted = 0
            for acc in accounts:
                conn.execute("""
                    INSERT INTO accounts (account_id, account_type, branch_city, occupation,
                                         income_bracket, declared_annual_income, risk_score, risk_level, role)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account_id) DO UPDATE SET
                        risk_score = excluded.risk_score,
                        risk_level = excluded.risk_level,
                        role = excluded.role,
                        occupation = CASE WHEN excluded.occupation != '' THEN excluded.occupation ELSE occupation END,
                        income_bracket = CASE WHEN excluded.income_bracket != '' THEN excluded.income_bracket ELSE income_bracket END,
                        declared_annual_income = CASE WHEN excluded.declared_annual_income > 0 THEN excluded.declared_annual_income ELSE declared_annual_income END,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    acc.get("account_id", ""),
                    acc.get("account_type", ""),
                    acc.get("branch_city", ""),
                    acc.get("occupation", ""),
                    acc.get("income_bracket", ""),
                    acc.get("declared_annual_income", 0),
                    acc.get("risk_score", 0),
                    acc.get("risk_level", "LOW"),
                    acc.get("role", "NORMAL"),
                ))
                inserted += 1
            conn.commit()
        return inserted

    def get_account(self, account_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            return dict(row) if row else None

    def account_exists(self, account_id: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT 1 FROM accounts WHERE account_id = ? LIMIT 1", (account_id,)).fetchone()
            return row is not None

    # ── Transactions ──
    def insert_transactions(self, transactions: List[Dict]) -> int:
        if not transactions:
            return 0
        with self._get_conn() as conn:
            inserted = 0
            for txn in transactions:
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO transactions
                        (txn_id, timestamp, source_account, dest_account, amount, channel, txn_type, is_laundering, ingestion_date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        txn.get("txn_id", ""),
                        txn.get("timestamp", ""),
                        txn.get("source_account", ""),
                        txn.get("dest_account", ""),
                        txn.get("amount", 0),
                        txn.get("channel", "unknown"),
                        txn.get("txn_type", "transfer"),
                        txn.get("is_laundering", 0),
                        txn.get("ingestion_date", datetime.now().strftime("%Y-%m-%d")),
                    ))
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
        return inserted

    def get_transactions_for_account(self, account_id: str, days: int = 7) -> List[Dict]:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM transactions
                WHERE (source_account = ? OR dest_account = ?)
                AND timestamp >= ?
                ORDER BY timestamp DESC
            """, (account_id, account_id, cutoff)).fetchall()
            return [dict(r) for r in rows]

    def get_transactions_between(self, start: str, end: str, limit: int = 10000) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM transactions
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (start, end, limit)).fetchall()
            return [dict(r) for r in rows]

    # ── Alerts ──
    def upsert_alert(self, alert: Dict) -> None:
        """Insert or refresh an alert. `account_ids` (list) is the canonical
        field; single-account callers (the realtime lightweight detectors)
        may pass `account_id` instead and it's normalised to a 1-item list.
        `detected_at` is set only on first insert and never overwritten, so
        it reliably answers "when was this first flagged" across repeated
        upserts of the same alert_id — `last_seen_at` tracks "still active,
        seen again" instead."""
        account_ids = alert.get("account_ids") or ([alert["account_id"]] if alert.get("account_id") else [])
        account_id = account_ids[0] if account_ids else alert.get("account_id", "")
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO alerts (alert_id, account_id, account_ids, risk_score, risk_level,
                                     pattern_type, status, severity, details_json, source,
                                     detected_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alert_id) DO UPDATE SET
                    risk_score = excluded.risk_score,
                    risk_level = excluded.risk_level,
                    severity = excluded.severity,
                    details_json = excluded.details_json,
                    status = excluded.status,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                alert.get("alert_id", ""),
                account_id,
                json.dumps(account_ids),
                alert.get("risk_score", 0),
                alert.get("risk_level", "LOW"),
                alert.get("pattern_type", ""),
                alert.get("status", "open"),
                alert.get("severity", "MEDIUM"),
                alert.get("details_json", ""),
                alert.get("source", "pipeline"),
                now,
                now,
            ))
            conn.commit()

    def _deserialize_alert(self, row: sqlite3.Row) -> Dict:
        d = dict(row)
        try:
            d["account_ids"] = json.loads(d.get("account_ids") or "[]")
        except (TypeError, ValueError):
            d["account_ids"] = [d["account_id"]] if d.get("account_id") else []
        return d

    def get_alerts(self, status: Optional[str] = None, risk_level: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> List[Dict]:
        with self._get_conn() as conn:
            query = "SELECT * FROM alerts WHERE 1=1"
            params: List[Any] = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if risk_level:
                query += " AND risk_level = ?"
                params.append(risk_level)
            query += " ORDER BY risk_score DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
            return [self._deserialize_alert(r) for r in rows]

    def get_alert(self, alert_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
            return self._deserialize_alert(row) if row else None

    def close_stale_alerts(self, active_ids: List[str]) -> List[str]:
        """Mark any currently-open alert whose id isn't in `active_ids` as
        'stale' (its underlying pattern no longer re-detected on the latest
        run). Returns the alert_ids that changed."""
        with self._get_conn() as conn:
            open_rows = conn.execute(
                "SELECT alert_id FROM alerts WHERE status = 'open'"
            ).fetchall()
            active_set = set(active_ids)
            to_close = [r["alert_id"] for r in open_rows if r["alert_id"] not in active_set]
            for alert_id in to_close:
                conn.execute(
                    "UPDATE alerts SET status = 'stale', updated_at = CURRENT_TIMESTAMP WHERE alert_id = ?",
                    (alert_id,),
                )
            conn.commit()
            return to_close

    # ── Ingestion metadata ──
    def record_ingestion(self, file_hash: str, filename: str, date: str,
                         num_transactions: int, num_accounts: int) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO ingestion_log (file_hash, filename, ingestion_date, num_transactions, num_accounts)
                VALUES (?, ?, ?, ?, ?)
            """, (file_hash, filename, date, num_transactions, num_accounts))
            conn.commit()

    def is_file_ingested(self, file_hash: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute("SELECT 1 FROM ingestion_log WHERE file_hash = ?", (file_hash,)).fetchone()
            return row is not None

    def get_ingestion_history(self, limit: int = 50) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ingestion_log ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Graph queries ──
    def get_ego_graph(self, account_id: str, radius: int = 2) -> Dict:
        """Get ego-graph of an account from DB (BFS up to radius hops)."""
        visited_accounts = set()
        frontier = {account_id}
        edges = []

        with self._get_conn() as conn:
            for _hop in range(radius):
                if not frontier:
                    break
                next_frontier = set()
                for acc in frontier:
                    if acc in visited_accounts:
                        continue
                    visited_accounts.add(acc)
                    rows = conn.execute("""
                        SELECT * FROM transactions
                        WHERE source_account = ? OR dest_account = ?
                        LIMIT 500
                    """, (acc, acc)).fetchall()
                    for r in rows:
                        row = dict(r)
                        edges.append(row)
                        neighbor = row["dest_account"] if row["source_account"] == acc else row["source_account"]
                        if neighbor not in visited_accounts:
                            next_frontier.add(neighbor)
                frontier = next_frontier

            # Get account info for all visited accounts
            all_accounts = visited_accounts | frontier
            nodes = []
            for acc in all_accounts:
                acc_row = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (acc,)).fetchone()
                if acc_row:
                    nodes.append(dict(acc_row))
                else:
                    nodes.append({"account_id": acc, "risk_score": 0, "risk_level": "LOW", "role": "UNKNOWN"})

        return {"nodes": nodes, "edges": edges, "center": account_id}

    def get_graph_filtered(self, risk_min: float = 0, risk_max: float = 100,
                           pattern: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           max_nodes: int = 100) -> Dict:
        """Get filtered subgraph from DB."""
        with self._get_conn() as conn:
            # Get filtered accounts
            query = "SELECT * FROM accounts WHERE risk_score >= ? AND risk_score <= ?"
            params: List[Any] = [risk_min, risk_max]
            query += " ORDER BY risk_score DESC LIMIT ?"
            params.append(max_nodes)
            account_rows = conn.execute(query, params).fetchall()
            nodes = [dict(r) for r in account_rows]
            account_ids = [n["account_id"] for n in nodes]

            if not account_ids:
                return {"nodes": [], "edges": []}

            # Get edges between these accounts
            placeholders = ",".join("?" * len(account_ids))
            edge_query = f"""
                SELECT * FROM transactions
                WHERE source_account IN ({placeholders})
                AND dest_account IN ({placeholders})
            """
            edge_params = account_ids + account_ids
            if since:
                edge_query += " AND timestamp >= ?"
                edge_params.append(since)
            if until:
                edge_query += " AND timestamp <= ?"
                edge_params.append(until)
            edge_query += " LIMIT 5000"

            edge_rows = conn.execute(edge_query, edge_params).fetchall()
            edges = [dict(r) for r in edge_rows]

        return {"nodes": nodes, "edges": edges}

    def get_account_count(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM accounts").fetchone()
            return row["cnt"] if row else 0

    def get_transaction_count(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM transactions").fetchone()
            return row["cnt"] if row else 0

    # ── Maintenance ──

    def delete_by_account_prefix(self, prefix: str) -> Dict[str, int]:
        like = f"{prefix}%"
        with self._get_conn() as conn:
            txn_cur = conn.execute(
                "DELETE FROM transactions WHERE source_account LIKE ? OR dest_account LIKE ?",
                (like, like),
            )
            alert_cur = conn.execute(
                "DELETE FROM alerts WHERE account_id LIKE ?", (like,)
            )
            acct_cur = conn.execute(
                "DELETE FROM accounts WHERE account_id LIKE ?", (like,)
            )
            conn.commit()
            return {
                "transactions_deleted": txn_cur.rowcount if txn_cur.rowcount >= 0 else 0,
                "alerts_deleted": alert_cur.rowcount if alert_cur.rowcount >= 0 else 0,
                "accounts_deleted": acct_cur.rowcount if acct_cur.rowcount >= 0 else 0,
            }

    # ── Cases ──

    def _deserialize_case(self, row: sqlite3.Row) -> Dict:
        d = dict(row)
        d["account_ids"] = json.loads(d["account_ids"])
        d["risk_scores"] = json.loads(d["risk_scores"])
        return d

    def create_case(self, case_data: Dict) -> Dict:
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO cases
                    (case_id, account_ids, risk_scores, pattern_type, notes,
                     investigator, status, graph_snapshot, str_reference,
                     created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_data["case_id"],
                    json.dumps(case_data.get("account_ids", [])),
                    json.dumps(case_data.get("risk_scores", {})),
                    case_data.get("pattern_type", "manual"),
                    case_data.get("notes", ""),
                    case_data.get("investigator", "Unassigned"),
                    case_data.get("status", "open"),
                    case_data.get("graph_snapshot", ""),
                    case_data.get("str_reference", ""),
                    now,
                    now,
                ),
            )
            conn.commit()
        result = self.get_case(case_data["case_id"])
        if result is None:
            raise RuntimeError(f"Failed to retrieve case {case_data['case_id']} after insert")
        return result

    def get_cases(self) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM cases ORDER BY created_at DESC"
            ).fetchall()
            return [self._deserialize_case(r) for r in rows]

    def get_case(self, case_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM cases WHERE case_id = ?", (case_id,)
            ).fetchone()
            return self._deserialize_case(row) if row else None

    def update_case_status(self, case_id: str, status: str, notes: str) -> Optional[Dict]:
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE cases SET status = ?, notes = ?, updated_at = ? WHERE case_id = ?",
                (status, notes, now, case_id),
            )
            conn.commit()
        return self.get_case(case_id)

    # ── Daily run summary ──

    def record_daily_run_summary(self, summary: Dict) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO daily_run_summary
                    (run_date, run_at, new_alert_ids, reactivated_alert_ids, stale_alert_ids,
                     total_accounts_flagged, total_alerts_open, accounts_ingested,
                     transactions_ingested, pipeline_summary_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_date) DO UPDATE SET
                    run_at = excluded.run_at,
                    new_alert_ids = excluded.new_alert_ids,
                    reactivated_alert_ids = excluded.reactivated_alert_ids,
                    stale_alert_ids = excluded.stale_alert_ids,
                    total_accounts_flagged = excluded.total_accounts_flagged,
                    total_alerts_open = excluded.total_alerts_open,
                    accounts_ingested = excluded.accounts_ingested,
                    transactions_ingested = excluded.transactions_ingested,
                    pipeline_summary_json = excluded.pipeline_summary_json
            """, (
                summary["run_date"],
                summary.get("run_at", datetime.now().isoformat()),
                json.dumps(summary.get("new_alert_ids", [])),
                json.dumps(summary.get("reactivated_alert_ids", [])),
                json.dumps(summary.get("stale_alert_ids", [])),
                summary.get("total_accounts_flagged", 0),
                summary.get("total_alerts_open", 0),
                summary.get("accounts_ingested", 0),
                summary.get("transactions_ingested", 0),
                json.dumps(summary.get("pipeline_summary", {}), default=str),
            ))
            conn.commit()

    def _deserialize_run_summary(self, row: sqlite3.Row) -> Dict:
        d = dict(row)
        for key in ("new_alert_ids", "reactivated_alert_ids", "stale_alert_ids"):
            try:
                d[key] = json.loads(d.get(key) or "[]")
            except (TypeError, ValueError):
                d[key] = []
        try:
            d["pipeline_summary"] = json.loads(d.pop("pipeline_summary_json", "") or "{}")
        except (TypeError, ValueError):
            d["pipeline_summary"] = {}
        return d

    def get_daily_run_summary(self, run_date: Optional[str] = None) -> Optional[Dict]:
        run_date = run_date or datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_run_summary WHERE run_date = ?", (run_date,)
            ).fetchone()
            return self._deserialize_run_summary(row) if row else None

    def get_recent_run_summaries(self, limit: int = 14) -> List[Dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM daily_run_summary ORDER BY run_date DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._deserialize_run_summary(r) for r in rows]

    # ── Detection rules ──

    @staticmethod
    def _deserialize_rule(row: sqlite3.Row) -> Dict:
        d = dict(row)
        try:
            d["rule_json"] = json.loads(d["rule_json"])
        except (TypeError, ValueError):
            d["rule_json"] = {"combinator": "AND", "conditions": []}
        d["enabled"] = bool(d["enabled"])
        d["is_builtin"] = bool(d["is_builtin"])
        return d

    def list_rules(self, enabled_only: bool = False) -> List[Dict]:
        query = "SELECT * FROM detection_rules"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY is_builtin DESC, name"
        with self._get_conn() as conn:
            rows = conn.execute(query).fetchall()
            return [self._deserialize_rule(r) for r in rows]

    def get_rule(self, rule_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM detection_rules WHERE rule_id = ?", (rule_id,)).fetchone()
            return self._deserialize_rule(row) if row else None

    def create_rule(self, rule: Dict) -> Dict:
        now = datetime.now().isoformat()
        rule_json = json.dumps(rule["rule_json"])
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO detection_rules
                    (rule_id, name, description, detection_type, severity, rule_json,
                     enabled, is_builtin, version, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?, ?)
            """, (
                rule["rule_id"], rule["name"], rule.get("description", ""), rule["detection_type"],
                rule.get("severity", "MEDIUM"), rule_json,
                int(rule.get("enabled", True)), rule.get("created_by", "user"), now, now,
            ))
            conn.execute("""
                INSERT INTO detection_rule_history (rule_id, version, rule_json, changed_by)
                VALUES (?, 1, ?, ?)
            """, (rule["rule_id"], rule_json, rule.get("created_by", "user")))
            conn.commit()
        return self.get_rule(rule["rule_id"])

    def update_rule(self, rule_id: str, updates: Dict) -> Optional[Dict]:
        existing = self.get_rule(rule_id)
        if not existing:
            return None
        new_version = existing["version"] + 1
        now = datetime.now().isoformat()
        name = updates.get("name", existing["name"])
        description = updates.get("description", existing["description"])
        severity = updates.get("severity", existing["severity"])
        rule_json = updates.get("rule_json", existing["rule_json"])
        enabled = updates.get("enabled", existing["enabled"])
        rule_json_str = json.dumps(rule_json)
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE detection_rules SET name=?, description=?, severity=?, rule_json=?,
                    enabled=?, version=?, updated_at=? WHERE rule_id=?
            """, (name, description, severity, rule_json_str, int(enabled), new_version, now, rule_id))
            conn.execute("""
                INSERT INTO detection_rule_history (rule_id, version, rule_json, changed_by)
                VALUES (?, ?, ?, ?)
            """, (rule_id, new_version, rule_json_str, updates.get("changed_by", "user")))
            conn.commit()
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str) -> bool:
        with self._get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM detection_rules WHERE rule_id = ? AND is_builtin = 0", (rule_id,)
            )
            conn.commit()
            return cur.rowcount > 0

    def set_rule_enabled(self, rule_id: str, enabled: bool) -> Optional[Dict]:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE detection_rules SET enabled=?, updated_at=? WHERE rule_id=?",
                (int(enabled), datetime.now().isoformat(), rule_id),
            )
            conn.commit()
        return self.get_rule(rule_id)


# ─── Neo4j Implementation ────────────────────────────────────────────────

class Neo4jAdapter(DatabaseAdapter):
    """Neo4j Aura free tier — graph-native storage."""

    def __init__(self):
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
            self._driver.verify_connectivity()
            logger.info("Connected to Neo4j at %s", NEO4J_URI)
        except Exception as e:
            logger.error("Failed to connect to Neo4j: %s — falling back to SQLite", e)
            raise

    def initialize(self):
        with self._driver.session() as session:
            # Create constraints and indexes
            constraints = [
                "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Account) REQUIRE a.account_id IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Transaction) REQUIRE t.txn_id IS UNIQUE",
                "CREATE CONSTRAINT IF NOT EXISTS FOR (al:Alert) REQUIRE al.alert_id IS UNIQUE",
                "CREATE INDEX IF NOT EXISTS FOR (a:Account) ON (a.risk_score)",
                "CREATE INDEX IF NOT EXISTS FOR (a:Account) ON (a.risk_level)",
                "CREATE INDEX IF NOT EXISTS FOR (t:Transaction) ON (t.timestamp)",
                "CREATE INDEX IF NOT EXISTS FOR (al:Alert) ON (al.status)",
            ]
            for c in constraints:
                try:
                    session.run(c)
                except Exception as e:
                    logger.warning("Constraint/index warning: %s", e)
        logger.info("Neo4j schema initialized")

    def close(self):
        if self._driver:
            self._driver.close()

    def upsert_accounts(self, accounts: List[Dict]) -> int:
        if not accounts:
            return 0
        with self._driver.session() as session:
            result = session.run("""
                UNWIND $accounts AS acc
                MERGE (a:Account {account_id: acc.account_id})
                SET a += acc
                RETURN count(a) as cnt
            """, accounts=accounts)
            return result.single()["cnt"]

    def get_account(self, account_id: str) -> Optional[Dict]:
        with self._driver.session() as session:
            result = session.run(
                "MATCH (a:Account {account_id: $id}) RETURN a", id=account_id
            )
            record = result.single()
            return dict(record["a"]) if record else None

    def account_exists(self, account_id: str) -> bool:
        with self._driver.session() as session:
            result = session.run(
                "MATCH (a:Account {account_id: $id}) RETURN count(a) > 0 AS exists", id=account_id
            )
            return result.single()["exists"]

    def insert_transactions(self, transactions: List[Dict]) -> int:
        if not transactions:
            return 0
        with self._driver.session() as session:
            # Batch in chunks of 1000
            total = 0
            for i in range(0, len(transactions), 1000):
                batch = transactions[i:i + 1000]
                result = session.run("""
                    UNWIND $txns AS t
                    MERGE (src:Account {account_id: t.source_account})
                    MERGE (dst:Account {account_id: t.dest_account})
                    MERGE (tx:Transaction {txn_id: t.txn_id})
                    SET tx += t
                    MERGE (src)-[:SENT]->(tx)
                    MERGE (tx)-[:RECEIVED_BY]->(dst)
                    RETURN count(tx) as cnt
                """, txns=batch)
                total += result.single()["cnt"]
            return total

    def get_transactions_for_account(self, account_id: str, days: int = 7) -> List[Dict]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._driver.session() as session:
            result = session.run("""
                MATCH (a:Account {account_id: $id})-[:SENT|RECEIVED_BY]-(t:Transaction)
                WHERE t.timestamp >= $cutoff
                RETURN t ORDER BY t.timestamp DESC LIMIT 5000
            """, id=account_id, cutoff=cutoff)
            return [dict(record["t"]) for record in result]

    def get_transactions_between(self, start: str, end: str, limit: int = 10000) -> List[Dict]:
        with self._driver.session() as session:
            result = session.run("""
                MATCH (t:Transaction)
                WHERE t.timestamp >= $start AND t.timestamp <= $end
                RETURN t ORDER BY t.timestamp DESC LIMIT $limit
            """, start=start, end=end, limit=limit)
            return [dict(record["t"]) for record in result]

    def upsert_alert(self, alert: Dict) -> None:
        account_ids = alert.get("account_ids") or ([alert["account_id"]] if alert.get("account_id") else [])
        props = dict(alert)
        props["account_ids"] = json.dumps(account_ids)
        props["account_id"] = account_ids[0] if account_ids else alert.get("account_id", "")
        now = datetime.now().isoformat()
        with self._driver.session() as session:
            session.run("""
                MERGE (al:Alert {alert_id: $alert_id})
                ON CREATE SET al.detected_at = $now
                SET al += $props, al.last_seen_at = $now
            """, alert_id=alert.get("alert_id"), props=props, now=now)

    def get_alerts(self, status: Optional[str] = None, risk_level: Optional[str] = None,
                   limit: int = 100, offset: int = 0) -> List[Dict]:
        with self._driver.session() as session:
            query = "MATCH (al:Alert) WHERE 1=1"
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            if status:
                query += " AND al.status = $status"
                params["status"] = status
            if risk_level:
                query += " AND al.risk_level = $risk_level"
                params["risk_level"] = risk_level
            query += " RETURN al ORDER BY al.risk_score DESC SKIP $offset LIMIT $limit"
            result = session.run(query, **params)
            return [self._deserialize_alert_node(record["al"]) for record in result]

    def get_alert(self, alert_id: str) -> Optional[Dict]:
        with self._driver.session() as session:
            result = session.run("MATCH (al:Alert {alert_id: $id}) RETURN al", id=alert_id)
            record = result.single()
            return self._deserialize_alert_node(record["al"]) if record else None

    def close_stale_alerts(self, active_ids: List[str]) -> List[str]:
        with self._driver.session() as session:
            result = session.run("""
                MATCH (al:Alert {status: 'open'})
                WHERE NOT al.alert_id IN $active_ids
                SET al.status = 'stale'
                RETURN al.alert_id AS alert_id
            """, active_ids=active_ids)
            return [record["alert_id"] for record in result]

    @staticmethod
    def _deserialize_alert_node(node) -> Dict:
        d = dict(node)
        try:
            d["account_ids"] = json.loads(d.get("account_ids") or "[]")
        except (TypeError, ValueError):
            d["account_ids"] = [d["account_id"]] if d.get("account_id") else []
        return d

    def record_ingestion(self, file_hash: str, filename: str, date: str,
                         num_transactions: int, num_accounts: int) -> None:
        with self._driver.session() as session:
            session.run("""
                MERGE (i:IngestionLog {file_hash: $hash})
                SET i.filename = $filename, i.ingestion_date = $date,
                    i.num_transactions = $num_txns, i.num_accounts = $num_accs,
                    i.created_at = datetime()
            """, hash=file_hash, filename=filename, date=date,
                num_txns=num_transactions, num_accs=num_accounts)

    def is_file_ingested(self, file_hash: str) -> bool:
        with self._driver.session() as session:
            result = session.run(
                "MATCH (i:IngestionLog {file_hash: $hash}) RETURN count(i) > 0 AS exists",
                hash=file_hash
            )
            return result.single()["exists"]

    def get_ingestion_history(self, limit: int = 50) -> List[Dict]:
        with self._driver.session() as session:
            result = session.run(
                "MATCH (i:IngestionLog) RETURN i ORDER BY i.created_at DESC LIMIT $limit",
                limit=limit
            )
            return [dict(record["i"]) for record in result]

    def get_ego_graph(self, account_id: str, radius: int = 2) -> Dict:
        with self._driver.session() as session:
            result = session.run("""
                MATCH path = (center:Account {account_id: $id})-[*1..$radius]-(neighbor)
                WHERE neighbor:Account OR neighbor:Transaction
                WITH center, collect(DISTINCT neighbor) AS neighbors, collect(path) AS paths
                UNWIND paths AS p
                UNWIND relationships(p) AS rel
                WITH center, neighbors,
                     startNode(rel) AS src, endNode(rel) AS dst, type(rel) AS relType
                RETURN center, neighbors, collect({src: src, dst: dst, type: relType}) AS rels
            """, id=account_id, radius=radius)
            record = result.single()
            if not record:
                return {"nodes": [], "edges": [], "center": account_id}

            nodes = [dict(record["center"])]
            for n in record["neighbors"]:
                nodes.append(dict(n))

            edges = []
            for r in record["rels"]:
                edges.append({
                    "source": dict(r["src"]).get("account_id", ""),
                    "target": dict(r["dst"]).get("account_id", ""),
                    "type": r["type"],
                })

            return {"nodes": nodes, "edges": edges, "center": account_id}

    def get_graph_filtered(self, risk_min: float = 0, risk_max: float = 100,
                           pattern: Optional[str] = None,
                           since: Optional[str] = None, until: Optional[str] = None,
                           max_nodes: int = 100) -> Dict:
        with self._driver.session() as session:
            query = """
                MATCH (a:Account)
                WHERE a.risk_score >= $risk_min AND a.risk_score <= $risk_max
                RETURN a ORDER BY a.risk_score DESC LIMIT $max_nodes
            """
            result = session.run(query, risk_min=risk_min, risk_max=risk_max, max_nodes=max_nodes)
            nodes = [dict(record["a"]) for record in result]
            account_ids = [n["account_id"] for n in nodes]

            if not account_ids:
                return {"nodes": [], "edges": []}

            # Get edges between these accounts
            edge_query = """
                MATCH (src:Account)-[:SENT]->(t:Transaction)-[:RECEIVED_BY]->(dst:Account)
                WHERE src.account_id IN $ids AND dst.account_id IN $ids
                RETURN src.account_id AS source, dst.account_id AS target,
                       t.amount AS amount, t.timestamp AS timestamp, t.channel AS channel
                LIMIT 5000
            """
            edge_result = session.run(edge_query, ids=account_ids)
            edges = [dict(record) for record in edge_result]

            return {"nodes": nodes, "edges": edges}

    def get_account_count(self) -> int:
        with self._driver.session() as session:
            result = session.run("MATCH (a:Account) RETURN count(a) AS cnt")
            return result.single()["cnt"]

    def get_transaction_count(self) -> int:
        with self._driver.session() as session:
            result = session.run("MATCH (t:Transaction) RETURN count(t) AS cnt")
            return result.single()["cnt"]

    def delete_by_account_prefix(self, prefix: str) -> Dict[str, int]:
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (a:Account) WHERE a.account_id STARTS WITH $prefix
                OPTIONAL MATCH (a)-[:SENT]->(t:Transaction)
                OPTIONAL MATCH (t)-[:RECEIVED_BY]->()
                WITH a, collect(DISTINCT t) AS txns
                FOREACH (tx IN txns | DETACH DELETE tx)
                DETACH DELETE a
                RETURN count(DISTINCT a) AS accounts_deleted
                """,
                prefix=prefix,
            )
            record = result.single()
            return {
                "transactions_deleted": -1,
                "alerts_deleted": -1,
                "accounts_deleted": record["accounts_deleted"] if record else 0,
            }


# ─── Factory ──────────────────────────────────────────────────────────────

_db_instance: Optional[DatabaseAdapter] = None


def get_database() -> DatabaseAdapter:
    """Get or create the database singleton."""
    global _db_instance
    if _db_instance is not None:
        return _db_instance

    if DB_BACKEND == "neo4j" and NEO4J_URI:
        try:
            _db_instance = Neo4jAdapter()
            _db_instance.initialize()
            logger.info("Using Neo4j backend")
            return _db_instance
        except Exception as e:
            logger.warning("Neo4j unavailable (%s), falling back to SQLite", e)

    _db_instance = SQLiteAdapter(SQLITE_PATH)
    _db_instance.initialize()
    logger.info("Using SQLite backend at %s", SQLITE_PATH)
    return _db_instance


def compute_file_hash(filepath: str) -> str:
    """Compute SHA256 hash of a file for idempotency."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
