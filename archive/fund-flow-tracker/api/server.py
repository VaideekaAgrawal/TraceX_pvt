"""
TraceX REST API — FastAPI server backed by the microservice layer.

All business logic lives in services/. This layer only handles:
- HTTP routing and request/response serialisation
- CORS
- Health endpoints
"""

import asyncio
import base64
import json
import logging
import os
import pathlib
import sys
import time
import traceback
import uuid
from collections import Counter
from typing import Any, Dict, List, Optional
from functools import lru_cache

import httpx
import numpy as np
import pandas as pd
from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# Configure logging FIRST so all service loggers output to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)

# Project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env before any infrastructure imports so env vars are available to config.py
_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

from infrastructure.config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from infrastructure.event_bus import bus, Topics
from infrastructure.health import health
from services.ingestion import IngestionService
from services.graph import GraphService
from services.detection import DetectionService
from services.investigation import InvestigationService
from services.monitoring import monitor
from services.realtime.stream_service import RealtimeStreamService, AlreadyRunningError
from services.pipeline import AnalysisPipeline
from services.detection.rule_engine import PrimitiveRegistry
from services.validation.rule_validator import RuleValidator

logger = logging.getLogger(__name__)

app = FastAPI(title="TraceX API", version="3.0.0",
              description="TraceX AML Intelligence System — microservice API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Service instances ────────────────────────────────────────────────────
ingestion_svc = IngestionService()
graph_svc = GraphService()
detection_svc = DetectionService()
investigation_svc = InvestigationService()
realtime_svc = RealtimeStreamService()
pipeline = AnalysisPipeline(ingestion_svc, graph_svc, detection_svc, investigation_svc)
rule_validator = RuleValidator()

# ── Realtime SSE connection tracking ─────────────────────────────────────
# Known limitation: bus.subscribe() has no unsubscribe, so queues from closed
# SSE connections stay registered as subscribers (harmless — they just stop
# being read from). This list is used only to estimate live queue depth for
# the dashboard; stale empty queues (qsize 0) are acceptable for demo scope.
_active_realtime_queues: List["asyncio.Queue"] = []


def _current_max_queue_depth() -> int:
    return max((q.qsize() for q in _active_realtime_queues), default=0)

# ── Response cache (TTL = 30s for expensive queries) ─────────────────────
_response_cache = TTLCache(maxsize=64, ttl=30)

# ── Shared state ─────────────────────────────────────────────────────────
_state: Dict[str, Any] = {}

# ── OpenRouter AI helper ──────────────────────────────────────────────────

_explain_cache: dict = {}


def _call_openrouter(prompt: str, max_tokens: int = 250) -> str:
    if not OPENROUTER_API_KEY:
        return "AI explanations not configured. Set OPENROUTER_API_KEY in .env"
    try:
        r = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:3000",
                "X-Title": "TraceX AML",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=20.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"Could not generate explanation: {str(e)}"


@app.on_event("startup")
async def _startup():
    """Ensure the database schema is created on boot, then bring the in-memory
    graph/detection state back up to date with whatever is already persisted —
    so a server restart or redeploy doesn't present an empty dashboard. If the
    DB is genuinely empty (first run), seed it with a small curated demo
    dataset instead of starting blank."""
    global _state
    from infrastructure.database import get_database as _get_db

    db = _get_db()

    if db.get_account_count() == 0 or db.get_transaction_count() == 0:
        try:
            from scripts.seed_demo_data import seed_if_empty
            seed_if_empty(db)
        except Exception:
            logger.exception("Demo data seeding failed — starting with an empty system")
            return

    if db.get_account_count() > 0 and db.get_transaction_count() > 0:
        try:
            result = pipeline.run_from_db()
            _state["accounts_df"] = result["accounts_df"]
            _state["transactions_df"] = result["transactions_df"]
            logger.info("Startup: rebuilt in-memory state from %d accounts / %d transactions in DB",
                        len(result["accounts_df"]), len(result["transactions_df"]))
        except Exception:
            logger.exception("Startup rebuild from DB failed — system will require /api/refresh")


def _require_ready():
    if not graph_svc.is_ready:
        raise HTTPException(503, "System not initialized. POST /api/init first.")


# ── Request models ───────────────────────────────────────────────────────

class InitRequest(BaseModel):
    source: str = "ibm_aml"
    filepath: Optional[str] = None
    max_rows: Optional[int] = None


class FundTrailRequest(BaseModel):
    account_id: str
    direction: str = "both"
    max_depth: int = 5


class EvidenceRequest(BaseModel):
    case_id: str
    account_ids: List[str]
    case_notes: str = ""


class CaseRequest(BaseModel):
    account_ids: List[str]
    typology: str
    priority: str = "P3"
    notes: str = ""


class CaseUpdateRequest(BaseModel):
    status: str
    notes: str = ""


class CaseResolveRequest(BaseModel):
    resolution: str
    is_true_positive: bool


class CaseCreate(BaseModel):
    case_id: str
    account_ids: List[str]
    risk_scores: Dict[str, float] = {}
    pattern_type: str = "manual"
    notes: str = ""
    investigator: str = "Unassigned"
    graph_snapshot: str = ""
    str_reference: str = ""


class CaseStatusUpdate(BaseModel):
    status: str  # open|in_progress|escalated|closed
    notes: str = ""


class RandomWalkRequest(BaseModel):
    start_node: str
    restart_prob: float = Field(default=0.15, ge=0.0, le=1.0)
    num_steps: int = Field(default=5000, ge=100, le=50000)


class RLFeedbackRequest(BaseModel):
    account_id: str
    is_true_positive: bool


class RLSimulateRequest(BaseModel):
    steps: int = Field(default=30, ge=1, le=100)
    scenario: str = "balanced"


class RuleCondition(BaseModel):
    primitive: str
    params: Dict[str, Any] = {}
    negate: bool = False


class RuleJson(BaseModel):
    combinator: str = "AND"
    conditions: List[RuleCondition]


class RuleCreateRequest(BaseModel):
    rule_id: str
    name: str
    description: str = ""
    detection_type: str
    severity: str = "MEDIUM"
    rule_json: RuleJson
    enabled: bool = True


class RuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    rule_json: Optional[RuleJson] = None
    enabled: Optional[bool] = None


class RuleDryRunRequest(BaseModel):
    detection_type: str = "custom"
    severity: str = "MEDIUM"
    rule_json: RuleJson


# ── Utility ──────────────────────────────────────────────────────────────

def _ts(val):
    if pd.isna(val):
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _safe(obj):
    if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
        return obj.isoformat() if hasattr(obj, "isoformat") else str(obj)
    if hasattr(obj, "item"):
        return obj.item()
    return obj


def _risk_level(score: float) -> str:
    if score >= 76: return "CRITICAL"
    if score >= 51: return "HIGH"
    if score >= 26: return "MEDIUM"
    return "LOW"


def _risk_color(score: float) -> str:
    return {"LOW": "#2ecc71", "MEDIUM": "#f39c12", "HIGH": "#e67e22", "CRITICAL": "#e74c3c"}[_risk_level(score)]


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

# ── Health ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return health.get_health()


@app.get("/health/live")
async def liveness():
    return {"status": "alive"}


@app.get("/health/ready")
async def readiness():
    return {"ready": graph_svc.is_ready}


# ── System init ──────────────────────────────────────────────────────────

@app.post("/api/init")
async def init_system(req: InitRequest):
    """Initialize the full pipeline from a data source."""
    global _state

    filepath = req.filepath
    if req.source == "ibm_aml" and not filepath:
        filepath = "data/HI-Small_Trans.csv"
    elif req.source == "paysim" and not filepath:
        filepath = "data/paysim.csv"

    accounts_df, txns_df = ingestion_svc.ingest(
        source=req.source, filepath=filepath, max_rows=req.max_rows,
    )
    result = pipeline.run(accounts_df, txns_df)

    _state["accounts_df"] = result["accounts_df"]
    _state["transactions_df"] = result["transactions_df"]
    _response_cache.clear()

    return {
        "status": "ok",
        "accounts": len(accounts_df),
        "transactions": len(txns_df),
        "pipeline_summary": result["pipeline_summary"],
    }


@app.post("/api/refresh")
async def refresh_from_db():
    """Rebuild the in-memory graph and run detection from existing DB data (no file needed)."""
    global _state

    try:
        result = pipeline.run_from_db()
    except ValueError as e:
        raise HTTPException(400, str(e))

    _state["accounts_df"] = result["accounts_df"]
    _state["transactions_df"] = result["transactions_df"]
    _response_cache.clear()

    return {
        "status": "ok",
        "accounts": len(result["accounts_df"]),
        "transactions": len(result["transactions_df"]),
        "pipeline_summary": result["pipeline_summary"],
    }


@app.post("/api/upload")
async def upload_csv(file: UploadFile = File(...), max_rows: Optional[int] = None):
    """Upload a CSV and run the full pipeline."""
    global _state

    df = pd.read_csv(file.file)
    accounts_df, txns_df = ingestion_svc.ingest(
        source="csv", dataframe=df, max_rows=max_rows,
    )
    result = pipeline.run(accounts_df, txns_df)

    _state["accounts_df"] = result["accounts_df"]
    _state["transactions_df"] = result["transactions_df"]
    _response_cache.clear()

    return {
        "status": "ok",
        "accounts": len(accounts_df),
        "transactions": len(txns_df),
        "pipeline_summary": result["pipeline_summary"],
    }


# ── Dashboard overview ───────────────────────────────────────────────────

@app.get("/api/overview")
async def get_overview():
    _require_ready()

    # Check cache first
    cache_key = "overview"
    if cache_key in _response_cache:
        return _response_cache[cache_key]

    graph_stats = graph_svc.get_stats()
    risk = detection_svc.risk_scores
    roles = detection_svc.roles
    accounts = _state.get("accounts_df")
    txns = _state.get("transactions_df")

    # Stats block matching frontend OverviewData.stats
    stats = {
        "num_nodes": graph_stats.get("num_nodes", 0),
        "num_edges": graph_stats.get("num_edges", 0),
        "num_components": graph_stats.get("num_components", 0),
        "density": graph_stats.get("density", 0),
        "avg_in_degree": graph_stats.get("avg_in_degree", 0),
        "avg_out_degree": graph_stats.get("avg_out_degree", 0),
    }

    # Risk distribution keyed as frontend expects (uppercase)
    risk_distribution = {
        "CRITICAL": sum(1 for s in risk.values() if s >= 76),
        "HIGH": sum(1 for s in risk.values() if 51 <= s < 76),
        "MEDIUM": sum(1 for s in risk.values() if 26 <= s < 51),
        "LOW": sum(1 for s in risk.values() if s < 26),
    }

    # Role distribution
    role_distribution = {}
    for r_info in roles.values():
        role = r_info.get("role", "UNKNOWN")
        role_distribution[role] = role_distribution.get(role, 0) + 1

    # Build detection types per account (for Patterns column in dashboard)
    det_types_by_account: dict = {}
    for det_type, dets in detection_svc.detection_results.items():
        for det in dets:
            for acc_id in det.account_ids:
                if acc_id not in det_types_by_account:
                    det_types_by_account[acc_id] = []
                if det_type not in det_types_by_account[acc_id]:
                    det_types_by_account[acc_id].append(det_type)

    # Top alerts — sorted by risk score desc
    top_alerts = []
    for acc_id, score in sorted(risk.items(), key=lambda x: x[1], reverse=True)[:50]:
        role_info = roles.get(acc_id, {"role": "UNKNOWN"})
        branch_city = ""
        acc_type = ""
        if accounts is not None:
            acc_row = accounts[accounts["account_id"] == acc_id]
            if len(acc_row) > 0:
                branch_city = str(acc_row.iloc[0].get("branch_city", "") or "")
                acc_type = str(acc_row.iloc[0].get("account_type", "") or "")
        top_alerts.append({
            "account_id": acc_id,
            "risk_score": round(score, 1),
            "risk_level": _risk_level(score),
            "risk_color": _risk_color(score),
            "role": role_info["role"],
            "branch_city": branch_city,
            "account_type": acc_type,
            "patterns": det_types_by_account.get(acc_id, []),
        })

    # Pattern counts
    det_summary = detection_svc.get_detection_summary()
    pattern_counts = {
        "layering": det_summary.get("layering", 0),
        "round_tripping": det_summary.get("round_trip", 0),
        "structuring": det_summary.get("structuring", 0),
        "dormant_activation": det_summary.get("dormancy", 0),
        "profile_mismatch": det_summary.get("profile_mismatch", 0),
    }

    # Total flagged (accounts with risk >= 51)
    total_flagged = risk_distribution["CRITICAL"] + risk_distribution["HIGH"]

    # Total amount
    total_amount = float(txns["amount"].sum()) if txns is not None and "amount" in txns.columns else 0

    result = {
        "stats": stats,
        "risk_distribution": risk_distribution,
        "role_distribution": role_distribution,
        "top_alerts": top_alerts,
        "pattern_counts": pattern_counts,
        "total_flagged": total_flagged,
        "total_anomalies": int(detection_svc.anomaly_results["is_anomaly"].sum()) if detection_svc.anomaly_results is not None else 0,
        "fraud_metrics": {k: _safe(v) for k, v in detection_svc.fraud_metrics.items()},
        "total_amount": total_amount,
        "avg_risk": round(sum(risk.values()) / max(len(risk), 1), 1),
    }
    _response_cache[cache_key] = result
    return result


@app.get("/api/dashboard/live")
async def dashboard_live():
    """Lightweight, frequently-pollable snapshot for a live-activity dashboard widget.
    Degrades gracefully (zeros) instead of 500ing if the system isn't initialized yet,
    since this may be polled before /api/init or while a realtime stream is running."""
    transactions_last_60s = 0
    alerts_last_60s = 0
    try:
        db = get_database()
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM transactions WHERE created_at >= datetime('now', '-60 seconds')"
            ).fetchone()
            transactions_last_60s = int(row["c"]) if row else 0
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM alerts WHERE created_at >= datetime('now', '-60 seconds')"
            ).fetchone()
            alerts_last_60s = int(row["c"]) if row else 0
    except Exception as e:
        logger.warning("dashboard_live: transaction/alert count query failed: %s", e)

    highest_risk_account_id = None
    highest_risk_score = None
    try:
        risk = detection_svc.risk_scores
        if risk:
            highest_risk_account_id, highest_risk_score = max(risk.items(), key=lambda kv: kv[1])
            highest_risk_score = round(float(highest_risk_score), 1)
    except Exception as e:
        logger.warning("dashboard_live: risk_scores lookup failed: %s", e)

    bus_stats = {}
    try:
        bus_stats = bus.get_stats()
    except Exception:
        pass

    return {
        "transactions_last_60s": transactions_last_60s,
        "alerts_last_60s": alerts_last_60s,
        "highest_risk_account_today": {
            "account_id": highest_risk_account_id,
            "score": highest_risk_score,
        },
        "event_bus_queue_depth": _current_max_queue_depth(),
        "dlq_depth": bus_stats.get("dlq_depth", 0),
    }


@app.get("/api/daily-summary")
async def daily_summary(date: Optional[str] = None):
    """What's new as of the most recent pipeline run for `date` (defaults to
    today): alerts flagged for the first time vs. still-active ones seen
    again, resolved to full Alert objects. Powers the dashboard's "Today's
    Activity" panel. 404s if no pipeline run has recorded a summary yet for
    that date."""
    db = get_database()
    row = db.get_daily_run_summary(date)
    if row is None:
        raise HTTPException(404, f"No run summary recorded for {date or 'today'} yet.")

    def _resolve(alert_ids: List[str]) -> List[Dict]:
        resolved = []
        for aid in alert_ids:
            a = db.get_alert(aid)
            if a:
                resolved.append(a)
        return resolved

    return {
        "run_date": row["run_date"],
        "run_at": row["run_at"],
        "new_alerts": _resolve(row["new_alert_ids"]),
        "reactivated_alerts": _resolve(row["reactivated_alert_ids"]),
        "stale_alert_ids": row["stale_alert_ids"],
        "total_accounts_flagged": row["total_accounts_flagged"],
        "total_alerts_open": row["total_alerts_open"],
        "accounts_ingested": row["accounts_ingested"],
        "transactions_ingested": row["transactions_ingested"],
    }


# ── Accounts ─────────────────────────────────────────────────────────────

@app.get("/api/accounts")
async def list_accounts():
    _require_ready()
    accounts = _state["accounts_df"]
    txns = _state["transactions_df"]
    risk = detection_svc.risk_scores
    roles = detection_svc.roles
    anomaly = detection_svc.anomaly_results
    fraud = detection_svc.fraud_results

    # Pre-compute flows
    out_flow = txns.groupby("source_account")["amount"].sum()
    in_flow = txns.groupby("dest_account")["amount"].sum()
    txn_count_src = txns.groupby("source_account").size()
    txn_count_dst = txns.groupby("dest_account").size()

    # Pre-build O(1) lookup maps to avoid O(n²) DataFrame scans inside the loop
    anomaly_score_map = (
        anomaly.set_index("account_id")["anomaly_score"].to_dict()
        if anomaly is not None and not anomaly.empty else {}
    )

    results = []
    for _, row in accounts.iterrows():
        acc_id = row["account_id"]
        score = risk.get(acc_id, 0)
        role_info = roles.get(acc_id, {"role": "UNKNOWN", "confidence": 0})
        anom_score = anomaly_score_map.get(acc_id, 0)

        t_in = float(in_flow.get(acc_id, 0))
        t_out = float(out_flow.get(acc_id, 0))
        t_count = int(txn_count_src.get(acc_id, 0)) + int(txn_count_dst.get(acc_id, 0))

        results.append({
            "account_id": acc_id,
            "account_type": row.get("account_type", ""),
            "branch_city": row.get("branch_city", ""),
            "occupation": row.get("occupation", ""),
            "income_bracket": row.get("income_bracket", ""),
            "declared_annual_income": float(row.get("declared_annual_income", 0)),
            "total_in_flow": round(t_in, 2),
            "total_out_flow": round(t_out, 2),
            "txn_count": t_count,
            "risk_score": round(score, 1),
            "risk_level": _risk_level(score),
            "risk_color": _risk_color(score),
            "role": role_info["role"],
            "role_confidence": round(role_info.get("confidence", 0), 2),
            "anomaly_score": round(anom_score, 1),
            "is_new": bool(row.get("is_new", False)),
        })

    return sorted(results, key=lambda x: x["risk_score"], reverse=True)


@app.get("/api/accounts/{account_id}")
async def get_account(account_id: str):
    _require_ready()
    accounts = _state["accounts_df"]
    txns = _state["transactions_df"]

    row = accounts[accounts["account_id"] == account_id]
    if len(row) == 0:
        raise HTTPException(404, f"Account {account_id} not found")
    acc = {k: _safe(v) for k, v in row.iloc[0].to_dict().items()}

    detail = detection_svc.get_account_detail(account_id, accounts, txns, graph_svc)

    features = detection_svc.features_df
    feat = {}
    if features is not None and account_id in features.index:
        feat = {k: round(float(v), 4) for k, v in features.loc[account_id].items()}

    acc_txns = txns[(txns["source_account"] == account_id) | (txns["dest_account"] == account_id)]
    recent = acc_txns.sort_values("timestamp", ascending=False).head(20)
    txn_list = [{
        "txn_id": t["txn_id"], "timestamp": _ts(t["timestamp"]),
        "source_account": t["source_account"], "dest_account": t["dest_account"],
        "amount": float(t["amount"]), "channel": t.get("channel", ""),
        "source_is_new": bool(t.get("source_is_new", False)),
        "dest_is_new": bool(t.get("dest_is_new", False)),
    } for _, t in recent.iterrows()]

    return {
        "account": acc,
        "risk_score": round(detail["risk_score"], 1),
        "risk_level": _risk_level(detail["risk_score"]),
        "role": detail["role"],
        "role_confidence": round(detail["role_confidence"], 2),
        "anomaly_score": round(detail["anomaly_score"], 1),
        "fraud_probability": round(detail["fraud_probability"], 4),
        "features": feat,
        "confidence": detail["confidence"],
        "priority": detail["priority"],
        "total_amount": detail["total_amount"],
        "counterparties": detail["counterparties"],
        "recent_transactions": txn_list,
    }


@app.get("/api/explain/account/{account_id}")
def explain_account(account_id: str, force: bool = False):
    """Generate a human-readable AI explanation for why an account was flagged."""
    global _explain_cache

    if not force and account_id in _explain_cache:
        return {"account_id": account_id, "explanation": _explain_cache[account_id], "cached": True}

    # Gather all available data about this account
    acc_df = _state.get("accounts_df")
    txn_df = _state.get("transactions_df")

    if acc_df is None or txn_df is None:
        raise HTTPException(status_code=503, detail="System not initialized. POST /api/init first.")

    acc_row = acc_df[acc_df["account_id"] == account_id]
    if acc_row.empty:
        raise HTTPException(status_code=404, detail="Account not found")

    acc = acc_row.iloc[0]

    # Risk + ML scores
    risk_score = detection_svc.risk_scores.get(account_id, 0)
    risk_level = _risk_level(risk_score)

    # Anomaly score from DataFrame
    anomaly_score = 0
    if detection_svc.anomaly_results is not None:
        ar = detection_svc.anomaly_results[detection_svc.anomaly_results["account_id"] == account_id]
        anomaly_score = float(ar["anomaly_score"].iloc[0]) if len(ar) > 0 else 0

    # Fraud probability from DataFrame
    fraud_prob = 0
    if detection_svc.fraud_results is not None:
        fr = detection_svc.fraud_results[detection_svc.fraud_results["account_id"] == account_id]
        fraud_prob = float(fr["fraud_prob"].iloc[0]) if len(fr) > 0 else 0

    # Network role from detection_svc.roles
    role_info = detection_svc.roles.get(account_id, {})
    role = role_info.get("role", "UNKNOWN")
    role_conf = role_info.get("confidence", 0)

    # Detected patterns
    detected_patterns = []
    for det_type, dets in detection_svc.detection_results.items():
        for det in dets:
            if account_id in det.account_ids:
                detected_patterns.append(det_type)

    # Transaction stats
    acc_txns = txn_df[(txn_df["source_account"] == account_id) | (txn_df["dest_account"] == account_id)]
    txn_count = len(acc_txns)
    total_in = float(txn_df[txn_df["dest_account"] == account_id]["amount"].sum())
    total_out = float(txn_df[txn_df["source_account"] == account_id]["amount"].sum())

    declared_income = float(acc.get("declared_annual_income", 0) or 0)
    income_ratio = (total_in / declared_income) if declared_income > 0 else 0
    occupation = str(acc.get("occupation", "Unknown"))
    account_type = str(acc.get("account_type", "Unknown"))
    branch_city = str(acc.get("branch_city", "Unknown"))

    # Top features from ML (using features_df)
    features = {}
    if detection_svc.features_df is not None and account_id in detection_svc.features_df.index:
        features = {k: float(v) for k, v in detection_svc.features_df.loc[account_id].items()}
    top_features = sorted(features.items(), key=lambda x: abs(x[1]), reverse=True)[:5] if features else []

    # Unique counterparties
    counterparties = len(set(
        list(txn_df[txn_df["source_account"] == account_id]["dest_account"]) +
        list(txn_df[txn_df["dest_account"] == account_id]["source_account"])
    ))

    pattern_text = ", ".join(detected_patterns) if detected_patterns else "No specific pattern matched — ML model flagged anomalous behaviour"
    feature_text = "; ".join([f"{k.replace('_',' ')}: {v:.2f}" for k, v in top_features]) if top_features else "N/A"

    prompt = f"""You are a senior financial crime analyst writing investigation briefings for compliance officers at a bank. Write a clear, professional 3-4 sentence explanation of why account {account_id} has been flagged as suspicious by our AML system.

Account Profile:
- Account ID: {account_id}
- Account Type: {account_type}
- Branch: {branch_city}
- Occupation: {occupation}
- Declared Annual Income: ₹{declared_income:,.0f}
- Total Inflow: ₹{total_in:,.0f}
- Total Outflow: ₹{total_out:,.0f}
- Transaction Count: {txn_count}
- Unique Counterparties: {counterparties}
- Income-to-Volume Ratio: {income_ratio:.1f}x declared income
- Risk Score: {risk_score:.1f}/100 ({risk_level})
- Network Role: {role} (confidence: {role_conf:.0%})
- Anomaly Score: {anomaly_score:.1f}/100
- Fraud Probability: {fraud_prob:.1%}

AML Patterns Detected: {pattern_text}
Key Behavioural Indicators: {feature_text}

Instructions:
- Write as a compliance officer would for a Suspicious Activity Report
- Use specific numbers from the data above
- Explain what the patterns mean in plain English (e.g. "layering" = moving funds through multiple accounts to obscure origin)
- End with a concrete recommended investigative action
- Do NOT use bullet points or headers — write flowing prose only
- Do NOT mention model names like XGBoost or Isolation Forest
- Maximum 4 sentences"""

    explanation = _call_openrouter(prompt, max_tokens=300)
    _explain_cache[account_id] = explanation

    return {"account_id": account_id, "explanation": explanation, "cached": False}


# ── Graph ────────────────────────────────────────────────────────────────

@app.get("/api/graph")
async def get_graph(
    max_nodes: int = Query(default=40, ge=1, le=500),
    max_edges: int = Query(default=150, ge=1, le=2000),
):
    _require_ready()
    risk = detection_svc.risk_scores
    roles = detection_svc.roles

    # Select exactly max_nodes highest-risk accounts that exist in the graph.
    # This bypasses get_renderable_subgraph(), which internally caps its seed at
    # max_nodes // 2 and then slices an unordered set — causing the UI to show far
    # fewer nodes than requested even when max_nodes is set to a large value.
    G = graph_svc.graph.G
    sorted_accs = sorted(risk.items(), key=lambda x: x[1], reverse=True)
    selected = [acc for acc, _ in sorted_accs if acc in G][:max_nodes]
    sub = G.subgraph(selected)

    nodes = [{"id": n, "risk_score": round(risk.get(n, 0), 1),
              "risk_level": _risk_level(risk.get(n, 0)),
              "risk_color": _risk_color(risk.get(n, 0)),
              "role": roles.get(n, {}).get("role", "UNKNOWN")}
             for n in sub.nodes()]

    all_edges = [{"source": u, "target": v, "amount": float(d.get("amount", 0)),
              "channel": d.get("channel", ""), "timestamp": _ts(d.get("timestamp"))}
             for u, v, _, d in sub.edges(keys=True, data=True)]

    # Cap edges to prevent browser overload — keep highest-amount edges
    if len(all_edges) > max_edges:
        all_edges.sort(key=lambda e: e["amount"], reverse=True)
        all_edges = all_edges[:max_edges]

    return {"nodes": nodes, "edges": all_edges}


@app.get("/api/graph/ego/{account_id}")
async def get_ego(
    account_id: str,
    radius: int = Query(default=2, ge=1, le=5),
    max_edges: int = Query(default=100, ge=1, le=2000),
):
    _require_ready()
    risk = detection_svc.risk_scores
    roles = detection_svc.roles
    sub = graph_svc.get_ego_subgraph(account_id, radius)

    nodes = [{"id": n, "risk_score": round(risk.get(n, 0), 1),
              "risk_level": _risk_level(risk.get(n, 0)),
              "risk_color": _risk_color(risk.get(n, 0)),
              "role": roles.get(n, {}).get("role", "UNKNOWN"),
              "is_center": n == account_id}
             for n in sub.nodes()]

    all_edges = [{"source": u, "target": v, "amount": float(d.get("amount", 0)),
              "channel": d.get("channel", ""), "timestamp": _ts(d.get("timestamp"))}
             for u, v, _, d in sub.edges(keys=True, data=True)]

    # Cap edges to prevent browser overload
    if len(all_edges) > max_edges:
        all_edges.sort(key=lambda e: e["amount"], reverse=True)
        all_edges = all_edges[:max_edges]

    return {"nodes": nodes, "edges": all_edges, "center": account_id}


@app.post("/api/graph/fund-trail")
async def get_fund_trail(req: FundTrailRequest):
    _require_ready()
    result = graph_svc.get_fund_trail(req.account_id, req.direction, req.max_depth)
    if "trails" in result:
        for trail in result["trails"]:
            for hop in trail:
                hop["timestamp"] = _ts(hop.get("timestamp"))
    return result


@app.post("/api/graph/random-walk")
async def random_walk(req: RandomWalkRequest):
    _require_ready()
    probs = graph_svc.random_walk(req.start_node, req.restart_prob, req.num_steps)
    risk = detection_svc.risk_scores
    roles = detection_svc.roles
    accomplices = []
    for acc_id, prob in sorted(probs.items(), key=lambda x: x[1], reverse=True)[:20]:
        if acc_id == req.start_node:
            continue
        score = risk.get(acc_id, 0)
        role_info = roles.get(acc_id, {"role": "UNKNOWN"})
        accomplices.append({
            "account_id": acc_id,
            "visit_probability": round(prob, 6),
            "risk_score": round(score, 1),
            "risk_level": _risk_level(score),
            "role": role_info["role"],
        })
    return {"start_node": req.start_node, "accomplices": accomplices}


@app.get("/api/graph/pattern/{pattern_type}")
async def get_pattern_subgraph(pattern_type: str, max_nodes: int = 60, max_edges: int = 200):
    """
    Get the subgraph of accounts flagged for a specific pattern type.
    Returns nodes + edges suitable for Neo4j-style pattern visualization.
    Supported types: layering, round_trip, structuring, dormancy, profile_mismatch
    """
    _require_ready()
    risk = detection_svc.risk_scores
    roles = detection_svc.roles

    # Find accounts involved in this pattern
    dets = detection_svc.detection_results.get(pattern_type, [])
    if not dets:
        return {"nodes": [], "edges": [], "pattern_type": pattern_type, "count": 0}

    pattern_accounts = set()
    for d in dets:
        pattern_accounts.update(d.account_ids)

    # Limit to max_nodes
    sorted_accs = sorted(pattern_accounts, key=lambda a: risk.get(a, 0), reverse=True)
    selected = sorted_accs[:max_nodes]

    if not selected:
        return {"nodes": [], "edges": [], "pattern_type": pattern_type, "count": 0}

    # Build subgraph from those accounts
    G = graph_svc.graph.G
    valid_nodes = [n for n in selected if n in G]
    if not valid_nodes:
        return {"nodes": [], "edges": [], "pattern_type": pattern_type, "count": len(selected)}

    sub = G.subgraph(valid_nodes)

    nodes = [{
        "id": n,
        "risk_score": round(risk.get(n, 0), 1),
        "risk_level": _risk_level(risk.get(n, 0)),
        "risk_color": _risk_color(risk.get(n, 0)),
        "role": roles.get(n, {}).get("role", "UNKNOWN"),
        "flagged_pattern": pattern_type,
    } for n in sub.nodes()]

    all_edges = [{
        "source": u, "target": v,
        "amount": float(d.get("amount", 0)),
        "channel": d.get("channel", ""),
        "timestamp": _ts(d.get("timestamp")),
    } for u, v, _, d in sub.edges(keys=True, data=True)]

    # Cap edges
    if len(all_edges) > max_edges:
        all_edges.sort(key=lambda e: e["amount"], reverse=True)
        all_edges = all_edges[:max_edges]

    return {
        "nodes": nodes,
        "edges": all_edges,
        "pattern_type": pattern_type,
        "count": len(dets),
        "total_flagged_accounts": len(pattern_accounts),
    }


@app.get("/api/graph/validate/{account_id}")
async def validate_graph(account_id: str):
    """
    Prove that a flagged account's patterns are backed by real graph-algorithm
    computation. Every number returned here comes from an actual algorithm call
    against the live graph — nothing is hardcoded or estimated.
    """
    _require_ready()
    risk = detection_svc.risk_scores
    roles = detection_svc.roles

    if account_id not in graph_svc.graph.G:
        raise HTTPException(404, f"Account {account_id} not found")

    # ── (b) Layering — temporal transaction chains touching this account
    # (computed BEFORE the subgraph so the chain's nodes can be fed into the
    #  subgraph builder — the visual graph and the "N chains found" stat below
    #  are then guaranteed to reference the same nodes)
    t0 = time.perf_counter()
    all_chains = graph_svc.graph.get_transaction_chains(min_hops=3, time_window_minutes=30)
    layering_detection_ms = (time.perf_counter() - t0) * 1000

    account_chains = [
        c for c in all_chains
        if any(hop.get("from") == account_id or hop.get("to") == account_id for hop in c)
    ]
    layering_chains_found = len(account_chains)
    shortest_chain = min((len(c) for c in account_chains), default=0)
    longest_chain = max((len(c) for c in account_chains), default=0)

    # ── (c) Round-trip cycles containing this account
    t0 = time.perf_counter()
    all_cycles = graph_svc.graph.detect_cycles(max_length=5, max_cycles=500)
    cycle_detection_ms = (time.perf_counter() - t0) * 1000

    account_cycles = [c for c in all_cycles if account_id in c]
    round_trip_cycles_found = len(account_cycles)
    shortest_cycle = min((len(c) for c in account_cycles), default=0)
    longest_cycle = max((len(c) for c in account_cycles), default=0)

    # ── (a) Ego subgraph — visual graph + node set used to scope everything else.
    # Always includes the center's direct neighbors; only reaches further to
    # nodes that are part of a cycle/chain found above (real evidence), and
    # caps a hub account's plain neighbors to the highest-value ones — instead
    # of a blind 2-hop BFS that would pull in most of the dataset.
    priority_nodes: set = set()
    for c in account_chains:
        for hop in c:
            priority_nodes.add(hop.get("from"))
            priority_nodes.add(hop.get("to"))
    for c in account_cycles:
        priority_nodes.update(c)

    t0 = time.perf_counter()
    sub = graph_svc.graph.get_validation_subgraph(account_id, priority_nodes=priority_nodes, max_nodes=40)
    graph_build_ms = (time.perf_counter() - t0) * 1000

    node_set = set(sub.nodes())

    nodes = [{"id": n, "risk_score": round(risk.get(n, 0), 1),
              "risk_level": _risk_level(risk.get(n, 0)),
              "risk_color": _risk_color(risk.get(n, 0)),
              "role": roles.get(n, {}).get("role", "UNKNOWN"),
              "is_center": n == account_id}
             for n in sub.nodes()]

    edges = [{"source": u, "target": v, "amount": float(d.get("amount", 0)),
              "channel": d.get("channel", ""), "timestamp": _ts(d.get("timestamp"))}
             for u, v, _, d in sub.edges(keys=True, data=True)]

    # ── (d) Centrality — timed separately so cache hits are visible
    centrality_cache_hit = bool(graph_svc.graph._centrality_cache)
    t0 = time.perf_counter()
    graph_svc.graph.compute_centrality()
    centrality_computation_ms = (time.perf_counter() - t0) * 1000

    # ── Detections scoped to this ego-subgraph's node set
    structuring_hits = set()
    dormancy_hits = 0
    profile_mismatch_hits = 0
    for det_type, dets in detection_svc.detection_results.items():
        for det in dets:
            hit_nodes = node_set.intersection(det.account_ids)
            if not hit_nodes:
                continue
            if det_type == "structuring":
                structuring_hits.update(hit_nodes)
            elif det_type == "dormancy":
                dormancy_hits += 1
            elif det_type == "profile_mismatch":
                profile_mismatch_hits += 1

    # ── False-positive gate — how many distinct detection types hit each account
    # in the ego-subgraph (mirrors the pattern used in explain_account above)
    signal_counts: Dict[str, int] = {n: 0 for n in node_set}
    for det_type, dets in detection_svc.detection_results.items():
        accounts_hit_by_type = set()
        for det in dets:
            accounts_hit_by_type.update(node_set.intersection(det.account_ids))
        for n in accounts_hit_by_type:
            signal_counts[n] += 1

    single_signal_accounts = sum(1 for c in signal_counts.values() if c == 1)
    multi_signal_accounts = sum(1 for c in signal_counts.values() if c >= 2)
    accounts_promoted_to_P1 = sum(1 for c in signal_counts.values() if c >= 3)

    # ── Why flagged — reuse the existing LLM explanation endpoint logic
    explain_result = explain_account(account_id)
    why_flagged = explain_result["explanation"]

    return {
        "account_id": account_id,
        "graph": {"nodes": nodes, "edges": edges, "center": account_id},
        "graph_validation": {
            "nodes": len(nodes),
            "edges": len(edges),
            "layering_chains_found": layering_chains_found,
            "shortest_chain": shortest_chain,
            "longest_chain": longest_chain,
            "round_trip_cycles_found": round_trip_cycles_found,
            "shortest_cycle": shortest_cycle,
            "longest_cycle": longest_cycle,
            "structuring_accounts": len(structuring_hits),
            "dormant_activations": dormancy_hits,
            "profile_mismatches": profile_mismatch_hits,
            "algorithm_runtime_ms": {
                "graph_build": round(graph_build_ms, 3),
                "layering_detection": round(layering_detection_ms, 3),
                "cycle_detection": round(cycle_detection_ms, 3),
                "centrality_computation": round(centrality_computation_ms, 3),
            },
            "centrality_cache_hit": centrality_cache_hit,
            "false_positive_gate": {
                "single_signal_accounts": single_signal_accounts,
                "multi_signal_accounts": multi_signal_accounts,
                "accounts_promoted_to_P1": accounts_promoted_to_P1,
            },
        },
        "why_flagged": why_flagged,
    }


# ── Detection results ───────────────────────────────────────────────────

@app.get("/api/detections")
async def get_detections():
    _require_ready()
    return {
        det_type: [d.to_dict() for d in dets]
        for det_type, dets in detection_svc.detection_results.items()
    }


@app.get("/api/detections/{detection_type}")
async def get_detection_type(detection_type: str):
    _require_ready()
    dets = detection_svc.detection_results.get(detection_type, [])
    return [d.to_dict() for d in dets]


@app.get("/api/model-metrics")
async def get_model_metrics():
    _require_ready()
    return {
        "isolation_forest": {
            "method": "Unsupervised",
            "contamination": f"{detection_svc.anomaly_detector.model.contamination:.0%}",
            "accounts_flagged": int(detection_svc.anomaly_results["is_anomaly"].sum()) if detection_svc.anomaly_results is not None else 0,
        },
        "xgboost": {
            "method": "Supervised (trained on labelled data)",
            **detection_svc.fraud_metrics,
            "feature_importance": detection_svc.fraud_classifier.get_feature_importance(),
        },
    }


# ── Investigation ───────────────────────────────────────────────────────

@app.get("/api/alerts")
async def list_alerts(status: Optional[str] = None):
    return [a.to_dict() for a in investigation_svc.list_alerts(status)]


@app.post("/api/cases")
def create_case(body: CaseCreate):
    """Create a new investigation case (SQLite-persisted)."""
    db = get_database()
    return db.create_case(body.dict())


@app.get("/api/cases")
def list_cases():
    """List all cases, newest first (SQLite-persisted)."""
    db = get_database()
    return db.get_cases()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    """Retrieve a single case by ID."""
    db = get_database()
    case = db.get_case(case_id)
    if not case:
        raise HTTPException(404, f"Case {case_id} not found")
    return case


@app.put("/api/cases/{case_id}/status")
def update_case_status(case_id: str, body: CaseStatusUpdate):
    """Update case status and notes."""
    db = get_database()
    case = db.update_case_status(case_id, body.status, body.notes)
    if not case:
        raise HTTPException(404, f"Case {case_id} not found")
    return case


@app.post("/api/evidence")
async def generate_evidence(req: EvidenceRequest):
    _require_ready()
    pack = investigation_svc.generate_evidence(
        req.case_id, req.account_ids,
        detection_svc.get_summary(graph_svc),
        _state["transactions_df"], _state["accounts_df"],
        req.case_notes,
    )
    return {
        "case_id": pack.case_id,
        "str_reference": pack.str_reference,
        "json_hash": pack.json_hash,
        "pdf_base64": base64.b64encode(pack.pdf_bytes).decode(),
        "generated_at": pack.generated_at,
    }


# ── Event bus stats ──────────────────────────────────────────────────────

@app.get("/api/bus/stats")
async def bus_stats():
    return bus.get_stats()


@app.get("/api/bus/dlq")
async def dlq_peek():
    items = bus.dlq.peek(20)
    return [{"event_id": i["event"]["event_id"], "error": i["error"],
             "consumer": i["consumer"], "failed_at": i["failed_at"]}
            for i in items if isinstance(i.get("event"), dict) or hasattr(i.get("event"), "event_id")]


# ═══════════════════════════════════════════════════════════════════════════
# FRONTEND-COMPATIBLE ENDPOINTS (Next.js dashboard)
# ═══════════════════════════════════════════════════════════════════════════


class EvidenceGenerateRequest(BaseModel):
    case_id: str
    account_ids: List[str]
    pattern_type: str = "Layering"
    case_notes: str = ""


@app.get("/api/health")
async def api_health():
    """Health endpoint expected by frontend."""
    return {
        "status": "ok",
        "initialized": graph_svc.is_ready,
        "accounts": len(_state.get("accounts_df", [])),
        "transactions": len(_state.get("transactions_df", [])),
    }


@app.get("/api/transactions")
async def get_transactions(limit: int = 100, offset: int = 0):
    """Paginated transaction list."""
    _require_ready()
    txns = _state["transactions_df"]
    total = len(txns)
    page = txns.iloc[offset:offset + limit]
    return {
        "total": total,
        "transactions": [{
            "txn_id": str(r.get("txn_id", "")),
            "timestamp": _ts(r.get("timestamp")),
            "source_account": r.get("source_account", ""),
            "dest_account": r.get("dest_account", ""),
            "amount": float(r.get("amount", 0)),
            "channel": r.get("channel", ""),
            "txn_type": r.get("txn_type", ""),
        } for _, r in page.iterrows()],
    }


@app.get("/api/anomaly")
async def get_anomaly():
    """Anomaly detection data for the frontend dashboard."""
    _require_ready()
    anomaly = detection_svc.anomaly_results

    # Anomaly scores
    anomaly_scores = []
    if anomaly is not None:
        for _, row in anomaly.iterrows():
            anomaly_scores.append({
                "account_id": row["account_id"],
                "anomaly_score": round(float(row["anomaly_score"]), 2),
            })

    # Feature importance from XGBoost
    feature_importance = detection_svc.fraud_classifier.get_feature_importance()

    # Investigation queue — merge risk, anomaly, fraud, roles
    accounts_df = _state.get("accounts_df")
    txns_df = _state.get("transactions_df")
    summaries = detection_svc.get_all_account_summaries(accounts_df, txns_df, graph_svc)
    queue = [{
        "account_id": s["account_id"],
        "risk_score": round(s["risk_score"], 1),
        "risk_level": _risk_level(s["risk_score"]),
        "risk_color": _risk_color(s["risk_score"]),
        "role": s["role"],
        "priority": s["priority"],
        "confidence_level": s["confidence_level"],
        "confidence_count": s["confidence_count"],
        "indicators": s["indicators"],
        "anomaly_score": round(s["anomaly_score"], 1),
        "fraud_probability": round(s["fraud_probability"], 4),
        "total_amount": round(s["total_amount"], 2),
        "branch_city": s["branch_city"],
    } for s in summaries]

    # Speed alerts — derive from layering detections (rapid multi-hop chains)
    speed_alerts = []
    layering = detection_svc.detection_results.get("layering", [])
    for det in layering[:20]:
        d = det.details
        hops = d.get("hops", 0)
        time_span = d.get("time_span_minutes", 0)
        if hops > 0 and time_span > 0:
            avg_min_per_hop = time_span / hops
            category = "ABNORMAL" if avg_min_per_hop < 2 else "VERY_FAST" if avg_min_per_hop < 5 else "FAST"
            speed_alerts.append({
                "accounts": d.get("accounts", det.account_ids),
                "category": category,
                "label": f"{hops}-hop chain in {time_span:.0f} min",
                "color": "#ef4444" if category == "ABNORMAL" else "#f97316" if category == "VERY_FAST" else "#eab308",
                "avg_minutes_per_hop": round(avg_min_per_hop, 1),
                "total_minutes": round(time_span, 1),
                "hops": hops,
                "total_amount": float(d.get("total_amount", 0)),
            })

    return {
        "anomaly_scores": anomaly_scores,
        "feature_importance": feature_importance,
        "investigation_queue": queue,
        "speed_alerts": speed_alerts,
    }


@app.get("/api/patterns")
async def get_patterns():
    """All detected patterns for the Pattern Detector page."""
    _require_ready()
    patterns = detection_svc.get_all_patterns()

    # Ensure every pattern item has account_ids for the frontend
    # The profile_mismatch detector returns details without account references
    for det_type, detections in detection_svc.detection_results.items():
        key = det_type
        if key == "round_trip":
            key = "round_tripping"
        elif key == "dormancy":
            key = "dormant_activation"

        if key in patterns and isinstance(patterns[key], list):
            # Rebuild with account_ids injected
            enriched = []
            for det in detections:
                item = dict(det.details)
                item["account_ids"] = det.account_ids
                item["severity"] = det.severity
                item["score"] = det.score
                enriched.append(item)
            patterns[key] = enriched

    # Build flagged accounts list
    flagged = set()
    for dets in detection_svc.detection_results.values():
        for d in dets:
            flagged.update(d.account_ids)
    return {
        "patterns": patterns,
        "flagged_accounts": list(flagged),
    }


@app.get("/api/patterns/first-suspicious/{account_id}")
async def get_first_suspicious(account_id: str):
    """Find the first suspicious transaction for an account."""
    _require_ready()
    txns = _state["transactions_df"]
    acc_txns = txns[(txns["source_account"] == account_id) | (txns["dest_account"] == account_id)].copy()
    if len(acc_txns) == 0:
        return {"found": False}

    acc_txns["timestamp"] = pd.to_datetime(acc_txns["timestamp"], errors="coerce")
    acc_txns = acc_txns.sort_values("timestamp")

    # Find first suspicious via z-score on amounts
    amounts = acc_txns["amount"].values
    if len(amounts) < 3:
        return {"found": False}

    mean_amt = float(amounts.mean())
    std_amt = float(amounts.std())
    if std_amt == 0:
        return {"found": False}

    for _, row in acc_txns.iterrows():
        z = (float(row["amount"]) - mean_amt) / std_amt
        if abs(z) > 2.5:
            return {
                "found": True,
                "data": {
                    "txn_id": str(row.get("txn_id", "")),
                    "timestamp": _ts(row.get("timestamp")),
                    "amount": float(row["amount"]),
                    "z_score": round(z, 3),
                    "detection_method": "Z-score outlier (>2.5σ)",
                    "source_account": row.get("source_account", ""),
                    "dest_account": row.get("dest_account", ""),
                    "channel": row.get("channel", ""),
                },
            }

    # If no z-score outlier, check if account is flagged by detections
    flagged = set()
    for dets in detection_svc.detection_results.values():
        for d in dets:
            if account_id in d.account_ids:
                flagged.add(d.detection_type)

    if flagged:
        first_txn = acc_txns.iloc[0]
        return {
            "found": True,
            "data": {
                "txn_id": str(first_txn.get("txn_id", "")),
                "timestamp": _ts(first_txn.get("timestamp")),
                "amount": float(first_txn["amount"]),
                "z_score": 0.0,
                "detection_method": f"Pattern detection: {', '.join(flagged)}",
            },
        }

    return {"found": False}


@app.get("/api/profile")
async def get_profile():
    """Profile analysis — income vs volume scatter and mismatches."""
    _require_ready()
    accounts = _state["accounts_df"]
    txns = _state["transactions_df"]
    risk = detection_svc.risk_scores

    # Compute actual volume per account
    volume = txns.groupby("source_account")["amount"].sum()
    volume_in = txns.groupby("dest_account")["amount"].sum()
    total_volume = volume.add(volume_in, fill_value=0)

    scatter_data = []
    mismatches = []

    for _, row in accounts.iterrows():
        acc_id = row["account_id"]
        declared = float(row.get("declared_annual_income", 0))
        actual = float(total_volume.get(acc_id, 0))
        occupation = str(row.get("occupation", "Unknown"))
        income_bracket = str(row.get("income_bracket", "Unknown"))

        if declared <= 0:
            continue

        ratio = actual / declared if declared > 0 else 0
        scatter_data.append({
            "account_id": acc_id,
            "declared_income": declared,
            "actual_volume": round(actual, 2),
            "occupation": occupation,
            "income_bracket": income_bracket,
            "ratio": round(ratio, 2),
        })

        if ratio > 3.0:
            mismatches.append({
                "account_id": acc_id,
                "occupation": occupation,
                "income_bracket": income_bracket,
                "declared_income": declared,
                "actual_volume": round(actual, 2),
                "ratio": round(ratio, 2),
                "risk_score": round(risk.get(acc_id, 0), 1),
            })

    # Sort mismatches by ratio desc
    mismatches.sort(key=lambda x: x["ratio"], reverse=True)
    return {
        "scatter_data": scatter_data[:500],  # Limit for frontend performance
        "mismatches": mismatches[:100],
    }


@app.get("/api/profile/{account_id}")
async def get_profile_peer(account_id: str):
    """Peer group analysis for a specific account."""
    _require_ready()
    accounts = _state["accounts_df"]
    txns = _state["transactions_df"]

    acc_row = accounts[accounts["account_id"] == account_id]
    if len(acc_row) == 0:
        raise HTTPException(404, f"Account {account_id} not found")

    acc = acc_row.iloc[0]
    occupation = str(acc.get("occupation", "Unknown"))
    income_bracket = str(acc.get("income_bracket", "Unknown"))
    declared = float(acc.get("declared_annual_income", 0))

    # Compute volume
    volume = txns.groupby("source_account")["amount"].sum()
    volume_in = txns.groupby("dest_account")["amount"].sum()
    total_volume = volume.add(volume_in, fill_value=0)
    actual = float(total_volume.get(account_id, 0))

    # Find peers (same occupation + income bracket)
    peers = accounts[(accounts["occupation"] == occupation) & (accounts["income_bracket"] == income_bracket)]
    peer_volumes = [float(total_volume.get(pid, 0)) for pid in peers["account_id"] if pid != account_id]

    import statistics
    peer_mean = statistics.mean(peer_volumes) if peer_volumes else 0
    peer_std = statistics.stdev(peer_volumes) if len(peer_volumes) > 1 else 1
    z_score = (actual - peer_mean) / peer_std if peer_std > 0 else 0

    return {
        "account_id": account_id,
        "occupation": occupation,
        "income_bracket": income_bracket,
        "declared_income": declared,
        "actual_volume": round(actual, 2),
        "peer_mean": round(peer_mean, 2),
        "peer_std": round(peer_std, 2),
        "z_score": round(z_score, 2),
        "peer_count": len(peer_volumes),
    }


@app.get("/api/channels")
async def get_channels():
    """Channel analytics data."""
    _require_ready()
    txns = _state["transactions_df"]

    if "channel" not in txns.columns:
        return {"summary": [], "sankey": [], "heatmap": [], "suspicious": []}

    # Summary per channel
    ch_summary = txns.groupby("channel").agg(
        count=("amount", "count"),
        total_amount=("amount", "sum"),
        avg_amount=("amount", "mean"),
        max_amount=("amount", "max"),
    ).reset_index()
    summary = [{
        "channel": row["channel"],
        "count": int(row["count"]),
        "total_amount": round(float(row["total_amount"]), 2),
        "avg_amount": round(float(row["avg_amount"]), 2),
        "max_amount": round(float(row["max_amount"]), 2),
    } for _, row in ch_summary.iterrows()]

    # Sankey-style flows (source_type → channel → dest_type)
    accounts = _state["accounts_df"]
    type_map = dict(zip(accounts["account_id"], accounts.get("account_type", "Unknown")))
    txns_sample = txns.head(50000)  # limit for performance
    txns_sample = txns_sample.copy()
    txns_sample["source_type"] = txns_sample["source_account"].map(type_map).fillna("Unknown")
    txns_sample["dest_type"] = txns_sample["dest_account"].map(type_map).fillna("Unknown")
    sankey_raw = txns_sample.groupby(["source_type", "channel", "dest_type"]).agg(
        count=("amount", "count"), total=("amount", "sum")
    ).reset_index()
    sankey = [{
        "source_type": row["source_type"], "channel": row["channel"],
        "dest_type": row["dest_type"], "count": int(row["count"]),
        "total": round(float(row["total"]), 2),
    } for _, row in sankey_raw.head(50).iterrows()]

    # Heatmap (channel × hour)
    heatmap = []
    txns_ts = txns.copy()
    txns_ts["timestamp"] = pd.to_datetime(txns_ts["timestamp"], errors="coerce")
    txns_ts["hour"] = txns_ts["timestamp"].dt.hour
    hm_raw = txns_ts.groupby(["channel", "hour"]).size().reset_index(name="count")
    heatmap = [{"channel": row["channel"], "hour": int(row["hour"]), "count": int(row["count"])}
               for _, row in hm_raw.iterrows()]

    # Suspicious channel usage (channels used by flagged accounts)
    flagged_accs = set()
    for dets in detection_svc.detection_results.values():
        for d in dets:
            flagged_accs.update(d.account_ids)

    suspicious = []
    if flagged_accs:
        flagged_txns = txns[txns["source_account"].isin(flagged_accs)]
        if len(flagged_txns) > 0 and "channel" in flagged_txns.columns:
            sus_ch = flagged_txns.groupby("channel").agg(
                count=("amount", "count"),
                total=("amount", "sum"),
                unique_accounts=("source_account", "nunique"),
            ).reset_index()
            suspicious = [{
                "channel": row["channel"], "count": int(row["count"]),
                "total": round(float(row["total"]), 2),
                "unique_accounts": int(row["unique_accounts"]),
            } for _, row in sus_ch.iterrows()]

    return {"summary": summary, "sankey": sankey, "heatmap": heatmap, "suspicious": suspicious}


@app.post("/api/evidence/generate")
async def generate_evidence_v2(req: EvidenceGenerateRequest):
    """Generate evidence pack — frontend-compatible endpoint."""
    _require_ready()
    pack = investigation_svc.generate_evidence(
        req.case_id, req.account_ids,
        detection_svc.get_summary(graph_svc),
        _state["transactions_df"], _state["accounts_df"],
        req.case_notes,
    )

    # Build summary for frontend
    txns = _state["transactions_df"]
    acc_txns = txns[txns["source_account"].isin(req.account_ids) | txns["dest_account"].isin(req.account_ids)]
    risk = detection_svc.risk_scores
    summary = {
        "total_transactions": int(len(acc_txns)),
        "total_amount": round(float(acc_txns["amount"].sum()), 2) if len(acc_txns) > 0 else 0,
        "max_risk_score": round(max((risk.get(a, 0) for a in req.account_ids), default=0), 1),
        "pattern_type": req.pattern_type,
        "accounts_investigated": len(req.account_ids),
    }

    return {
        "case_id": pack.case_id,
        "summary": summary,
        "pdf_base64": base64.b64encode(pack.pdf_bytes).decode(),
        "json_data": pack.json_payload if pack.json_payload else "{}",
    }


# ── Monitoring & Observability ───────────────────────────────────────────

@app.get("/api/metrics")
async def get_metrics():
    """Pipeline observability metrics and alerts."""
    return monitor.get_metrics()


@app.post("/api/metrics/acknowledge/{alert_index}")
async def acknowledge_alert(alert_index: int):
    """Acknowledge an alert."""
    success = monitor.acknowledge_alert(alert_index)
    if not success:
        raise HTTPException(404, "Alert not found")
    return {"acknowledged": True}


# ═══════════════════════════════════════════════════════════════════════════
# EOD INGESTION & DATABASE ENDPOINTS (Production-grade)
# ═══════════════════════════════════════════════════════════════════════════

from services.ingestion.eod_service import EODIngestionService
from infrastructure.database import get_database

eod_svc = EODIngestionService()


class IngestRequest(BaseModel):
    filepath: str
    date: Optional[str] = None
    source: str = "bank_system"
    max_rows: Optional[int] = None
    force: bool = False


_PROJECT_ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ALLOWED_INGEST_DIRS = [
    _PROJECT_ROOT / "data",
    _PROJECT_ROOT / "data" / "uploads",
]


def _safe_ingest_path(filepath: str) -> pathlib.Path:
    """Validate that the requested filepath is within an allowed directory."""
    try:
        resolved = pathlib.Path(filepath).resolve()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid file path")
    allowed = any(
        str(resolved).startswith(str(d.resolve()))
        for d in _ALLOWED_INGEST_DIRS
    )
    if not allowed:
        raise HTTPException(status_code=400, detail="File path is outside allowed directories")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return resolved


@app.post("/api/ingest")
async def ingest_eod(req: IngestRequest):
    """
    Ingest a daily EOD transaction CSV file (by path on server).

    Performs incremental analysis:
    - New accounts: detect patterns on today's data
    - Existing accounts: detect patterns on today + last 7 days
    """
    safe_path = _safe_ingest_path(req.filepath)
    try:
        result = eod_svc.ingest_daily_file(
            filepath=str(safe_path),
            date=req.date,
            max_rows=req.max_rows,
            force=req.force,
        )
        if result.get("status") in ("completed", "skipped"):
            try:
                pipeline_result = pipeline.run_from_db()
                _state["accounts_df"] = pipeline_result["accounts_df"]
                _state["transactions_df"] = pipeline_result["transactions_df"]
                _response_cache.clear()
                result["pipeline_summary"] = pipeline_result["pipeline_summary"]
                result["alert_diff"] = {k: v for k, v in pipeline_result["alert_diff"].items() if k != "alerts"}
            except ValueError as e:
                result["pipeline_warning"] = str(e)
        return result
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Ingestion failed: %s", e)
        raise HTTPException(500, f"Ingestion failed: {str(e)}")


@app.post("/api/ingest/upload")
async def ingest_upload(
    file: UploadFile = File(...),
    date: Optional[str] = Form(None),
    force: bool = Form(False),
):
    """
    Upload a CSV file for EOD ingestion via multipart form.
    The file is saved temporarily, processed, and results returned.
    After ingestion, the in-memory graph is refreshed with the new data.
    """
    import tempfile
    import shutil

    original_name = file.filename or "upload.csv"
    basename = os.path.basename(original_name)
    if not basename.lower().endswith(".csv"):
        raise HTTPException(400, "Only CSV files are accepted")

    # Use a UUID prefix to prevent path traversal and filename collisions
    safe_name = f"{uuid.uuid4().hex}_{basename}"

    # Save uploaded file to data/uploads/
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    dest_path = os.path.join(upload_dir, safe_name)

    try:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {str(e)}")
    finally:
        file.file.close()

    # Run ingestion
    try:
        result = eod_svc.ingest_daily_file(
            filepath=dest_path,
            date=date,
            force=force,
        )

        # After successful ingestion, rebuild in-memory state from full DB (cumulative)
        if result.get("status") in ("completed", "skipped"):
            try:
                # --- Upload-specific data for result summary (preview, charts) ---
                try:
                    upload_accounts_df, upload_txns_df = ingestion_svc.ingest(
                        source="ibm_aml", filepath=dest_path
                    )
                except Exception:
                    upload_accounts_df, upload_txns_df = ingestion_svc.ingest(
                        source="csv", filepath=dest_path
                    )

                # Row preview — first 20 rows with string timestamps
                preview_rows = upload_txns_df.head(20).copy()
                if "timestamp" in preview_rows.columns:
                    preview_rows["timestamp"] = preview_rows["timestamp"].astype(str)
                if "amount" in preview_rows.columns:
                    preview_rows["amount"] = preview_rows["amount"].round(2)

                # Attach source account's occupation/declared income for the preview.
                # Prefer reading Source_Occupation/Source_Declared_Income straight off the raw
                # uploaded CSV (authoritative — matches what eod_service._normalize will persist).
                # Fall back to the legacy IBMAMLParser's accounts_df (random synth) only if the
                # CSV doesn't carry real profile columns.
                _prof_attached = False
                try:
                    _raw_header = pd.read_csv(dest_path, nrows=0).columns.tolist()
                    if {"Account", "Source_Occupation", "Source_Declared_Income"}.issubset(_raw_header):
                        _raw_prof = pd.read_csv(
                            dest_path, usecols=["Account", "Source_Occupation", "Source_Declared_Income"]
                        )
                        _raw_prof["Account"] = _raw_prof["Account"].astype(str).str.strip()
                        _raw_prof = _raw_prof.drop_duplicates("Account").set_index("Account")
                        _raw_prof = _raw_prof.rename(columns={
                            "Source_Occupation": "occupation",
                            "Source_Declared_Income": "declared_annual_income",
                        })
                        preview_rows = preview_rows.merge(
                            _raw_prof, how="left", left_on="source_account", right_index=True
                        )
                        _prof_attached = True
                except Exception as e:
                    logger.warning("Could not read raw profile columns for preview: %s", e)

                if not _prof_attached and (
                    upload_accounts_df is not None
                    and "occupation" in upload_accounts_df.columns
                    and "declared_annual_income" in upload_accounts_df.columns
                ):
                    _acc_lookup = upload_accounts_df.set_index("account_id")[
                        ["occupation", "declared_annual_income"]
                    ]
                    preview_rows = preview_rows.merge(
                        _acc_lookup, how="left", left_on="source_account", right_index=True
                    )

                if "occupation" in preview_rows.columns:
                    preview_rows["occupation"] = preview_rows["occupation"].fillna("Unknown")
                if "declared_annual_income" in preview_rows.columns:
                    preview_rows["declared_annual_income"] = pd.to_numeric(
                        preview_rows["declared_annual_income"], errors="coerce"
                    ).fillna(0).round(0)

                result["row_preview"] = preview_rows.to_dict("records")

                # Hourly activity from upload timestamps
                if "timestamp" in upload_txns_df.columns:
                    ts = pd.to_datetime(upload_txns_df["timestamp"], errors="coerce").dropna()
                    if len(ts) > 0:
                        hourly = ts.dt.strftime("%H:00").value_counts().sort_index()
                        result["hourly_activity"] = [
                            {"hour": h, "count": int(c)} for h, c in hourly.items()
                        ]
                    else:
                        result["hourly_activity"] = []
                else:
                    result["hourly_activity"] = []

                # Top 5 accounts by transaction count in this upload
                src_counts = upload_txns_df.groupby("source_account").agg(
                    txn_count=("txn_id", "count"), total_amount=("amount", "sum")
                )
                dst_counts = upload_txns_df.groupby("dest_account").agg(
                    txn_count=("txn_id", "count"), total_amount=("amount", "sum")
                )
                combined = src_counts.add(dst_counts, fill_value=0).sort_values(
                    "txn_count", ascending=False
                ).head(5)
                result["top_accounts"] = [
                    {
                        "account_id": str(acc),
                        "txn_count": int(row["txn_count"]),
                        "total_amount": round(float(row["total_amount"]), 2),
                    }
                    for acc, row in combined.iterrows()
                ]

                # --- Run the full pipeline once over the cumulative DB dataset ---
                # (previously this rebuilt the graph/detection inline here, AFTER
                # ingest_daily_file() had already run its own lightweight 7-detector
                # pass over just this file — i.e. detection ran twice per upload,
                # with this second pass silently overwriting the first pass's
                # alerts. AnalysisPipeline.run_from_db() is now the only place
                # detection runs for an EOD ingest.)
                pipeline_result = pipeline.run_from_db()
                accounts_df = pipeline_result["accounts_df"]
                txns_df = pipeline_result["transactions_df"]
                _state["accounts_df"] = accounts_df
                _state["transactions_df"] = txns_df
                _response_cache.clear()
                result["system_refreshed"] = True
                result["alert_diff"] = {k: v for k, v in pipeline_result["alert_diff"].items() if k != "alerts"}
                logger.info("System state refreshed from full DB after upload (%d accounts, %d txns)",
                            len(accounts_df), len(txns_df))

                # --- Upload-specific summary extras ---
                try:
                    _risk_colors = {"CRITICAL": "#ef4444", "HIGH": "#f97316", "MEDIUM": "#eab308", "LOW": "#22c55e"}
                    _cum_acc = _state.get("accounts_df")

                    # Use detection_svc.risk_scores (computed in-memory) — NOT accounts_df risk_score (always 0 in DB)
                    _rs_map = detection_svc.risk_scores  # {account_id: float}
                    _anom_map = detection_svc.get_summary().anomaly_scores  # {account_id: float}
                    _role_map = {str(r["account_id"]): str(r.get("role", "NORMAL"))
                                 for _, r in _cum_acc.iterrows()} if _cum_acc is not None and len(_cum_acc) > 0 else {}
                    _income_map = {str(r["account_id"]): float(r.get("declared_annual_income", 0) or 0)
                                   for _, r in _cum_acc.iterrows()} if _cum_acc is not None and len(_cum_acc) > 0 else {}
                    _occ_map = {str(r["account_id"]): str(r.get("occupation", "Unknown") or "Unknown")
                                for _, r in _cum_acc.iterrows()} if _cum_acc is not None and len(_cum_acc) > 0 else {}

                    def _rl_from_score(rs: float) -> str:
                        if rs >= 75: return "CRITICAL"
                        if rs >= 50: return "HIGH"
                        if rs >= 25: return "MEDIUM"
                        return "LOW"

                    # Build per-account pattern list from detection_results
                    # Structure: {det_type: [DetectionResult(account_ids=[...])]}
                    _account_patterns: dict = {}
                    for _det_type, _dets in detection_svc.detection_results.items():
                        for _det in _dets:
                            for _acc_id in getattr(_det, "account_ids", []):
                                _account_patterns.setdefault(_acc_id, [])
                                if _det_type not in _account_patterns[_acc_id]:
                                    _account_patterns[_acc_id].append(_det_type)

                    _upload_ids = set(upload_txns_df["source_account"].astype(str)) | set(upload_txns_df["dest_account"].astype(str))
                    _inflow = upload_txns_df.groupby("dest_account")["amount"].sum()
                    _outflow = upload_txns_df.groupby("source_account")["amount"].sum()

                    # Field 1: graph_data (top 80 accounts by appearance)
                    _acc_counter: Counter = Counter()
                    for _, _r in upload_txns_df.iterrows():
                        _acc_counter[str(_r["source_account"])] += 1
                        _acc_counter[str(_r["dest_account"])] += 1
                    _top_ids = set(a for a, _ in _acc_counter.most_common(80))
                    _nodes = []
                    for _aid in _top_ids:
                        _rs = float(_rs_map.get(_aid, 0.0))
                        _rl = _rl_from_score(_rs)
                        _role = _role_map.get(_aid, "NORMAL")
                        _nodes.append({"id": _aid, "risk_score": _rs, "risk_level": _rl,
                                       "risk_color": _risk_colors.get(_rl, "#22c55e"), "role": _role})
                    _edges = []
                    for _, _r in upload_txns_df.iterrows():
                        _src, _dst = str(_r["source_account"]), str(_r["dest_account"])
                        if _src in _top_ids and _dst in _top_ids:
                            _edges.append({"source": _src, "target": _dst,
                                           "amount": float(_r.get("amount", 0)),
                                           "channel": str(_r.get("channel", "unknown")),
                                           "timestamp": str(_r.get("timestamp", ""))})
                    result["graph_data"] = {"nodes": _nodes, "edges": _edges[:500]}

                    # Field 2: priority_accounts (top 50 from CSV by risk_score)
                    _priority_accounts = []
                    for _aid in _upload_ids:
                        _rs = float(_rs_map.get(_aid, 0.0))
                        _rl = _rl_from_score(_rs)
                        _role = _role_map.get(_aid, "NORMAL")
                        _ps = 0
                        if _rl == "CRITICAL": _ps += 40
                        elif _rl == "HIGH": _ps += 25
                        elif _rl == "MEDIUM": _ps += 10
                        _vol = float(_inflow.get(_aid, 0)) + float(_outflow.get(_aid, 0))
                        if _vol > 10_000_000: _ps += 20
                        elif _vol > 1_000_000: _ps += 10
                        if _rs >= 90: _ps += 30
                        elif _rs >= 70: _ps += 20
                        elif _rs >= 50: _ps += 10
                        if _ps >= 88: _prio = "P1"
                        elif _ps >= 58: _prio = "P2"
                        elif _ps >= 28: _prio = "P3"
                        else: _prio = "P4"
                        _pats = _account_patterns.get(_aid, [])
                        _anom = float(_anom_map.get(_aid, 0))
                        _priority_accounts.append({
                            "account_id": _aid, "risk_score": round(_rs, 1), "risk_level": _rl,
                            "priority": _prio, "role": _role, "patterns": _pats,
                            "total_inflow": round(float(_inflow.get(_aid, 0)), 2),
                            "total_outflow": round(float(_outflow.get(_aid, 0)), 2),
                            "anomaly_score": round(_anom, 3),
                        })
                    _priority_accounts.sort(key=lambda x: x["risk_score"], reverse=True)
                    result["priority_accounts"] = _priority_accounts[:50]

                    # Field 3: channel_distribution
                    if "channel" in upload_txns_df.columns:
                        _ch = upload_txns_df["channel"].value_counts()
                        result["channel_distribution"] = [{"channel": str(c), "count": int(n)} for c, n in _ch.items()]
                    else:
                        result["channel_distribution"] = []

                    # Field 4: profile_mismatches (use income from DB via _income_map)
                    _total_vol = _inflow.add(_outflow, fill_value=0)
                    _profile_mm = []
                    for _aid in _upload_ids:
                        _declared = _income_map.get(_aid, 0.0)
                        if _declared <= 0:
                            continue
                        _actual = float(_total_vol.get(_aid, 0))
                        _ratio = _actual / _declared
                        if _ratio > 2.0:
                            _profile_mm.append({
                                "account_id": _aid,
                                "occupation": _occ_map.get(_aid, "Unknown"),
                                "declared_income": round(_declared, 0),
                                "actual_volume": round(_actual, 2),
                                "ratio": round(_ratio, 2),
                                "risk_score": round(float(_rs_map.get(_aid, 0.0)), 1),
                            })
                    _profile_mm.sort(key=lambda x: x["ratio"], reverse=True)
                    result["profile_mismatches"] = _profile_mm[:20]

                    # Field 5: speed_alerts (top 5 high-velocity senders)
                    _txn_counts = upload_txns_df["source_account"].value_counts()
                    _speed_alerts = []
                    for _aid, _cnt in _txn_counts.head(10).items():
                        _aid = str(_aid)
                        _rs = float(_rs_map.get(_aid, 0.0))
                        _speed_alerts.append({
                            "account_id": _aid,
                            "txn_count": int(_cnt),
                            "risk_level": _rl_from_score(_rs),
                        })
                        if len(_speed_alerts) >= 5:
                            break
                    result["speed_alerts"] = _speed_alerts

                except Exception as _extras_err:
                    logger.warning("Could not compute upload summary extras: %s", _extras_err, exc_info=True)

            except Exception as refresh_err:
                logger.warning("Could not refresh in-memory state: %s", refresh_err)
                result["system_refreshed"] = False
                result["refresh_warning"] = str(refresh_err)

        return result
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Upload ingestion failed: %s", e)
        raise HTTPException(500, f"Ingestion failed: {str(e)}")


@app.get("/api/ingest/status")
async def ingestion_status():
    """Get ingestion pipeline status and history."""
    return eod_svc.get_ingestion_status()


@app.get("/api/ingest/history")
async def ingestion_history():
    """Get recent ingestion history."""
    db = get_database()
    return db.get_ingestion_history(limit=50)


# ═══════════════════════════════════════════════════════════════════════════
# REAL-TIME STREAMING DEMO (SSE)
# ═══════════════════════════════════════════════════════════════════════════
#
# Streams data/tracex_realtime_demo.csv one transaction at a time through the
# real incremental detection pipeline (EODIngestionService.ingest_transaction_rows),
# publishing genuine detection results — not pre-computed replay data — over
# Server-Sent Events so the frontend can show alerts landing live.

@app.post("/api/realtime/start")
async def realtime_start():
    """Kick off the real-time demo stream. 409s if one is already in progress."""
    try:
        realtime_svc.start(eod_svc)
    except AlreadyRunningError as e:
        raise HTTPException(409, str(e))
    return {"status": "started", "total": realtime_svc.status()["total"]}


@app.get("/api/realtime/status")
async def realtime_status():
    return realtime_svc.status()


@app.get("/api/realtime/stream")
async def realtime_stream():
    """SSE stream of realtime.transaction / realtime.alert / realtime.done events."""
    queue: "asyncio.Queue" = asyncio.Queue()
    _active_realtime_queues.append(queue)

    for topic in (Topics.REALTIME_TRANSACTION, Topics.REALTIME_ALERT, Topics.REALTIME_DONE):
        bus.subscribe(topic, queue.put_nowait)

    async def _event_generator():
        try:
            while True:
                event = await queue.get()
                payload = {
                    "topic": event.topic,
                    "data": event.payload,
                    "timestamp": event.timestamp.isoformat(),
                }
                yield f"data: {json.dumps(payload)}\n\n"
                if event.topic == Topics.REALTIME_DONE:
                    break
        finally:
            try:
                _active_realtime_queues.remove(queue)
            except ValueError:
                pass

    return StreamingResponse(_event_generator(), media_type="text/event-stream")


# ── Filtered Graph Endpoints ─────────────────────────────────────────────

@app.get("/api/graph/filtered")
async def get_graph_filtered(
    risk_min: float = Query(default=0, ge=0, le=100),
    risk_max: float = Query(default=100, ge=0, le=100),
    pattern: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    max_nodes: int = Query(default=80, ge=1, le=500),
    role: Optional[str] = None,
):
    """
    Get filtered graph from the in-memory graph engine.
    Supports filtering by risk level, pattern type, time range, role.
    """
    _require_ready()
    risk = detection_svc.risk_scores
    roles = detection_svc.roles

    # Filter accounts by risk range
    filtered_accounts = [
        acc_id for acc_id, score in risk.items()
        if risk_min <= score <= risk_max
    ]

    # Filter by role if specified
    if role:
        filtered_accounts = [
            acc_id for acc_id in filtered_accounts
            if roles.get(acc_id, {}).get("role", "UNKNOWN") == role.upper()
        ]

    # Filter by pattern if specified
    if pattern:
        pattern_accounts = set()
        dets = detection_svc.detection_results.get(pattern, [])
        for d in dets:
            pattern_accounts.update(d.account_ids)
        filtered_accounts = [a for a in filtered_accounts if a in pattern_accounts]

    # Sort by risk score desc and limit
    filtered_accounts.sort(key=lambda a: risk.get(a, 0), reverse=True)
    filtered_accounts = filtered_accounts[:max_nodes]

    if not filtered_accounts:
        return {"nodes": [], "edges": [], "meta": {"total_matching": 0}}

    # Build subgraph from in-memory graph
    sub = graph_svc.graph.G.subgraph(filtered_accounts)

    nodes = [{
        "id": n,
        "risk_score": round(risk.get(n, 0), 1),
        "risk_level": _risk_level(risk.get(n, 0)),
        "risk_color": _risk_color(risk.get(n, 0)),
        "role": roles.get(n, {}).get("role", "UNKNOWN"),
    } for n in sub.nodes()]

    since_ts = pd.Timestamp(since) if since else None
    until_ts = pd.Timestamp(until) if until else None

    edges = []
    for u, v, _, d in sub.edges(keys=True, data=True):
        ts = d.get("timestamp")
        # Apply time filter if specified
        if since_ts or until_ts:
            try:
                ts_val = pd.Timestamp(ts) if ts is not None else None
            except Exception:
                ts_val = None
            if since_ts and (ts_val is None or ts_val < since_ts):
                continue
            if until_ts and (ts_val is None or ts_val > until_ts):
                continue
        edges.append({
            "source": u, "target": v,
            "amount": float(d.get("amount", 0)),
            "channel": d.get("channel", ""),
            "timestamp": _ts(ts),
        })

    # Cap edges to prevent browser overload
    if len(edges) > 300:
        edges.sort(key=lambda e: e["amount"], reverse=True)
        edges = edges[:300]

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "total_matching": len(filtered_accounts),
            "nodes_returned": len(nodes),
            "edges_returned": len(edges),
        },
    }


# ── Paginated Transactions with Filters ──────────────────────────────────

@app.get("/api/transactions/filtered")
async def get_transactions_filtered(
    account_id: Optional[str] = None,
    channel: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    is_laundering: Optional[int] = None,
    risk_level: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
):
    """
    Paginated transaction list with comprehensive filters.
    Supports filtering by account, channel, amount range, date range, and risk level.
    """
    _require_ready()
    txns = _state["transactions_df"].copy()

    # Apply filters
    if account_id:
        txns = txns[(txns["source_account"] == account_id) | (txns["dest_account"] == account_id)]
    if channel:
        txns = txns[txns["channel"] == channel]
    if min_amount is not None:
        txns = txns[txns["amount"] >= min_amount]
    if max_amount is not None:
        txns = txns[txns["amount"] <= max_amount]
    if since:
        txns["timestamp"] = pd.to_datetime(txns["timestamp"], errors="coerce")
        txns = txns[txns["timestamp"] >= pd.to_datetime(since)]
    if until:
        txns["timestamp"] = pd.to_datetime(txns["timestamp"], errors="coerce")
        txns = txns[txns["timestamp"] <= pd.to_datetime(until)]
    if is_laundering is not None and "is_laundering" in txns.columns:
        txns = txns[txns["is_laundering"] == is_laundering]

    # Filter by risk level of source account
    if risk_level:
        risk = detection_svc.risk_scores
        level_accounts = [
            acc_id for acc_id, score in risk.items()
            if _risk_level(score) == risk_level.upper()
        ]
        txns = txns[txns["source_account"].isin(level_accounts)]

    total = len(txns)

    # Sort
    if sort_by in txns.columns:
        ascending = sort_order.lower() != "desc"
        txns = txns.sort_values(sort_by, ascending=ascending)

    # Paginate
    page = txns.iloc[offset:offset + limit]

    transactions = [{
        "txn_id": str(r.get("txn_id", "")),
        "timestamp": _ts(r.get("timestamp")),
        "source_account": r.get("source_account", ""),
        "dest_account": r.get("dest_account", ""),
        "amount": float(r.get("amount", 0)),
        "channel": r.get("channel", ""),
        "txn_type": r.get("txn_type", ""),
    } for _, r in page.iterrows()]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "transactions": transactions,
    }


# ── DB Health ────────────────────────────────────────────────────────────

@app.get("/api/db/stats")
async def db_stats():
    """Database statistics."""
    try:
        db = get_database()
        return {
            "status": "connected",
            "accounts": db.get_account_count(),
            "transactions": db.get_transaction_count(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Metric Explanations ──────────────────────────────────────────────────

METRIC_EXPLANATIONS = {
    "risk_score": "Risk Score (0–100) combines outputs from three independent systems: an XGBoost machine learning classifier trained on transaction behaviour, an Isolation Forest anomaly detector, and graph centrality measures. A score above 80 indicates the account appears in the top tier of all three systems simultaneously.",
    "anomaly_score": "Anomaly Score measures how statistically unusual an account's behaviour is compared to all other accounts in the dataset. It is computed by an Isolation Forest model trained on 28 features including transaction velocity, amount variance, channel diversity, and time-of-day patterns. Scores above 70 indicate behaviour that falls outside normal ranges for the account's occupation and income bracket.",
    "fraud_probability": "Fraud Probability is the raw output probability from the XGBoost classifier (0–100%). It reflects the model's confidence that this account's transaction pattern resembles known money laundering cases in the training data. A probability above 50% does not mean confirmed fraud — it means the account warrants investigator review.",
    "role": "Network Role classifies the account's function in the transaction graph. MULE accounts primarily receive and forward funds. COLLECTOR accounts aggregate from many sources. SMURFER accounts make many small structured deposits. SOURCE accounts are primary fund originators. SINK accounts are final destinations. TRANSIENT accounts appear briefly and disappear.",
    "layering": "Layering is an AML typology where funds are moved through multiple intermediate accounts (typically 3 or more hops) in rapid succession to obscure the original source. Each transfer makes it harder to trace the money back to its origin. This account appears as an intermediate node in at least one such chain.",
    "round_trip": "Round-trip or circular flow is detected when funds sent by this account eventually return to it — directly or through intermediaries. This is a strong indicator of fictitious transactions designed to create an appearance of legitimate business activity.",
    "structuring": "Structuring (also called Smurfing) is the practice of breaking large amounts into smaller transactions — typically just below the ₹10 lakh CTR reporting threshold — to avoid regulatory detection. This account shows a statistical clustering of transaction amounts in the ₹9–9.9L range.",
    "fan_out": "Fan-Out pattern occurs when a single account distributes funds to an unusually large number of recipients in a short time window. This can indicate a money mule coordinator account that is distributing laundered funds across the network.",
    "fan_in": "Fan-In pattern occurs when a single account receives funds from an unusually large number of sources. Combined with rapid outflow, this indicates a collector account in a money laundering network.",
    "dormancy": "Dormant Account Activation flags accounts that had very low or zero activity for an extended period and then suddenly began high-volume transactions. This pattern is used by money launderers who acquire or reactivate old accounts to avoid triggering new-account monitoring rules.",
    "profile_mismatch": "Profile Mismatch is detected when an account's actual transaction volume significantly exceeds what would be expected given the account holder's declared occupation and income bracket. A daily wage earner transacting ₹50 lakh per month is an example of a profile mismatch.",
    "speed_alert": "Speed Alert flags transaction chains where funds moved between 3 or more accounts faster than normal banking settlement times. FAST = under 4 hours, VERY_FAST = under 1 hour, ABNORMAL = under 15 minutes. Rapid movement is a hallmark of automated layering.",
    "priority_p1": "P1 (Critical) accounts require action today. They have been flagged by multiple independent detection systems with high confidence, often showing 3+ AML typologies simultaneously. These cases represent the highest likelihood of active money laundering.",
    "priority_p2": "P2 (High Priority) accounts should be reviewed within 24 hours. They show strong signals from at least one major detection system and may have 1–2 AML typologies. These cases are likely to result in STR filing after investigation.",
    "priority_p3": "P3 (Medium) accounts should be reviewed within the week. They show moderate anomaly signals or a single AML typology with lower confidence. These may be false positives but warrant review.",
    "priority_p4": "P4 (Low) accounts are in the monitoring queue. They show mild statistical anomalies that do not yet meet the threshold for formal review. These accounts should be watched for escalating activity.",
    "str": "Suspicious Transaction Report (STR) is a mandatory filing with the Financial Intelligence Unit – India (FIU-IND) under the Prevention of Money Laundering Act (PMLA). Banks are required to file an STR within 7 days of detecting suspicious activity. The STR includes account details, transaction history, and the basis for suspicion.",
    "ego_graph": "The Ego Graph shows the direct neighbourhood of a selected account — all accounts it has transacted with (1st hop) and their connections (2nd hop). This helps investigators understand the account's immediate financial network and identify whether suspicious behaviour is isolated or part of a larger connected network.",
    "fund_trail": "Fund Trail traces the complete path of money from a source account through all intermediate transfers to its final destination. It helps investigators answer the question: where did this money come from, and where did it end up?",
    "accomplices": "Find Accomplices uses a random walk algorithm to identify accounts that are statistically likely to be connected to the selected account's suspicious activity, even if there is no direct transaction link. It surfaces hidden network relationships.",
    "total_flagged": "Total Flagged is the count of accounts that triggered at least one AML detection rule or received a risk score above the monitoring threshold. This does not mean all flagged accounts are committing fraud — it means each one requires investigator review to determine if a Suspicious Transaction Report should be filed.",
}


@app.get("/api/explain/metric/{metric_name}")
def explain_metric(metric_name: str):
    """Return a plain-English explanation of a dashboard metric or AML typology."""
    explanation = METRIC_EXPLANATIONS.get(metric_name)
    if not explanation:
        return {"metric": metric_name, "explanation": f"No explanation available for metric: {metric_name}"}
    return {"metric": metric_name, "explanation": explanation}


@app.get("/api/explain/metrics")
def explain_all_metrics():
    """Return all metric explanations as a single dictionary."""
    return METRIC_EXPLANATIONS


# ── RL — LinUCB Contextual Bandit (Adaptive Investigation Queue) ──────────
#
# Demo-scope online learning layer on top of the static P1-P4 queue: the
# agent re-ranks accounts by UCB score, and every investigator TP/FP verdict
# updates it in O(d^2) time. See services/rl/bandit.py for the algorithm.

@app.get("/api/rl/queue")
async def rl_investigation_queue():
    """RL-ranked investigation queue — accounts sorted by UCB score (exploration + exploitation)."""
    _require_ready()
    accounts_df = _state.get("accounts_df")
    txns_df = _state.get("transactions_df")

    result = investigation_svc.get_prioritized_queue(accounts_df, txns_df, detection_svc.get_summary())
    for r in result["queue"]:
        r["risk_level"] = _risk_level(r["risk_score"])

    return {"queue": result["queue"][:50], "agent_stats": result["agent_stats"]}


@app.post("/api/rl/feedback")
async def rl_feedback(body: RLFeedbackRequest):
    """Investigator submits a TP/FP verdict — the RL agent updates online (O(d^2))."""
    _require_ready()
    txns_df = _state.get("transactions_df")
    accounts_df = _state.get("accounts_df")

    result = investigation_svc.submit_feedback(
        body.account_id, body.is_true_positive, accounts_df, txns_df, detection_svc.get_summary()
    )
    if result is None:
        raise HTTPException(404, f"Account {body.account_id} not found")

    return {"status": "updated", **result}


@app.get("/api/rl/weights")
async def rl_learned_weights():
    """Current learned feature weights — full interpretability for compliance review."""
    return investigation_svc.get_rl_weights()


@app.post("/api/rl/simulate")
async def rl_simulate(body: RLSimulateRequest):
    """Demo endpoint: replay N synthetic feedback events to show the agent learning live,
    without needing real investigator history."""
    return investigation_svc.simulate_rl_feedback(body.scenario, body.steps)


# ── Rule Engine ──────────────────────────────────────────────────────────
# Lets an analyst edit any existing detector's thresholds (e.g. round-trip's
# return ratio 0.85 -> 0.70) or define genuinely new patterns — all DB-backed,
# no code deploy. See services/detection/rule_engine.py for the primitive
# catalog and Tier 1 (single primitive) / Tier 2 (AND/OR composite) model.

@app.get("/api/rules/primitives")
async def list_rule_primitives():
    """Every primitive's parameter schema + defaults — drives the frontend's
    dynamic condition-builder form."""
    return PrimitiveRegistry.list_primitives()


@app.get("/api/rules")
async def list_rules(enabled_only: bool = False):
    db = get_database()
    return db.list_rules(enabled_only=enabled_only)


@app.get("/api/rules/{rule_id}")
async def get_rule(rule_id: str):
    db = get_database()
    rule = db.get_rule(rule_id)
    if rule is None:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return rule


@app.post("/api/rules")
async def create_rule(req: RuleCreateRequest):
    db = get_database()
    if db.get_rule(req.rule_id) is not None:
        raise HTTPException(409, f"Rule {req.rule_id} already exists")

    rule_json = req.rule_json.dict()
    validation = rule_validator.validate(rule_json)
    if not validation.passed:
        raise HTTPException(422, {"violations": validation.violations})

    return db.create_rule({
        "rule_id": req.rule_id, "name": req.name, "description": req.description,
        "detection_type": req.detection_type, "severity": req.severity,
        "rule_json": rule_json, "enabled": req.enabled,
    })


@app.put("/api/rules/{rule_id}")
async def update_rule(rule_id: str, req: RuleUpdateRequest):
    db = get_database()
    existing = db.get_rule(rule_id)
    if existing is None:
        raise HTTPException(404, f"Rule {rule_id} not found")

    updates: Dict[str, Any] = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.description is not None:
        updates["description"] = req.description
    if req.severity is not None:
        updates["severity"] = req.severity
    if req.enabled is not None:
        updates["enabled"] = req.enabled
    if req.rule_json is not None:
        rule_json = req.rule_json.dict()
        validation = rule_validator.validate(rule_json)
        if not validation.passed:
            raise HTTPException(422, {"violations": validation.violations})
        updates["rule_json"] = rule_json

    return db.update_rule(rule_id, updates)


@app.delete("/api/rules/{rule_id}")
async def delete_rule(rule_id: str):
    db = get_database()
    existing = db.get_rule(rule_id)
    if existing is None:
        raise HTTPException(404, f"Rule {rule_id} not found")
    if existing["is_builtin"]:
        raise HTTPException(403, "Built-in rules cannot be deleted — disable it instead.")
    db.delete_rule(rule_id)
    return {"status": "deleted", "rule_id": rule_id}


@app.post("/api/rules/{rule_id}/enable")
async def enable_rule(rule_id: str):
    db = get_database()
    rule = db.set_rule_enabled(rule_id, True)
    if rule is None:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return rule


@app.post("/api/rules/{rule_id}/disable")
async def disable_rule(rule_id: str):
    db = get_database()
    rule = db.set_rule_enabled(rule_id, False)
    if rule is None:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return rule


@app.post("/api/rules/dry-run")
async def dry_run_rule(req: RuleDryRunRequest):
    """Evaluate a draft rule against the currently-loaded data with no side
    effects, so an analyst can preview impact before saving/enabling it."""
    _require_ready()
    rule_json = req.rule_json.dict()
    validation = rule_validator.validate(rule_json)
    if not validation.passed:
        raise HTTPException(422, {"violations": validation.violations})

    accounts_df = _state.get("accounts_df")
    txns_df = _state.get("transactions_df")
    return detection_svc.rule_engine.dry_run(
        rule_json, req.detection_type, req.severity, graph_svc.graph, accounts_df, txns_df,
    )
