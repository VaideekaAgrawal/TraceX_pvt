#!/usr/bin/env python3
"""
TraceX — Full System Validation Script
======================================
Generates synthetic data with known ground truth, runs the full pipeline
across 3 days (incremental), and prints a structured validation report.

Usage:
    cd fund-flow-tracker
    python scripts/validate_system.py

What gets validated:
  1. Ingestion         — IBM-AML CSV parsing, FX conversion, account deduplication
  2. Graph             — node/edge counts, PageRank, betweenness
  3. Feature Extraction— 29 features, no NaN/Inf, correct distributions
  4. Isolation Forest  — anomaly rate, fraud vs clean score separation
  5. XGBoost           — F1, AUC-ROC, Precision, Recall (temporal split)
  6. Layering          — recall on planted chains
  7. Round-Trip        — recall on planted cycles
  8. Structuring       — recall on planted sub-₹10L structuring
  9. Dormancy          — recall on planted dormant-burst accounts
  10. Profile Mismatch — recall on planted income mismatches
  11. Ensemble Scoring — fraud > clean score separation, score range
  12. Account Continuation — Day 1 → Day 2 → Day 3 returning/new breakdown
  13. Role Classification  — SOURCE/MULE/SINK/NORMAL distribution
"""
import os, sys, time, logging, json, textwrap
from datetime import datetime, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.WARNING,                       # suppress service noise
    format="%(levelname)s %(name)s: %(message)s",
)
logging.getLogger("infrastructure").setLevel(logging.ERROR)
logging.getLogger("services").setLevel(logging.ERROR)
logging.getLogger("xgboost").setLevel(logging.ERROR)

from services.ingestion.service import IngestionService
from services.graph.service import GraphService
from services.detection.service import DetectionService

# ─────────────────────────────────────────────────────────────────────────────
# ANSI colours for the terminal report
# ─────────────────────────────────────────────────────────────────────────────
G = "\033[92m"   # green
Y = "\033[93m"   # yellow
R = "\033[91m"   # red
B = "\033[94m"   # blue
W = "\033[1m"    # bold
E = "\033[0m"    # reset

def _pass(msg): return f"{G}✅ PASS{E}  {msg}"
def _warn(msg): return f"{Y}⚠️  WARN{E}  {msg}"
def _fail(msg): return f"{R}❌ FAIL{E}  {msg}"
def _info(msg): return f"{B}ℹ️  {E}  {msg}"

HEADER = "=" * 72

def section(title):
    print(f"\n{W}{HEADER}{E}")
    print(f"{W}  {title}{E}")
    print(f"{W}{HEADER}{E}")


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic data builder — known ground truth
# ─────────────────────────────────────────────────────────────────────────────

BANKS   = ["ICICI", "HDFC", "SBI", "AXIS", "KOTAK", "CANARA", "YES", "PNB"]
CHANNELS= ["NEFT", "RTGS", "IMPS", "UPI", "Wire", "Credit Card", "ACH"]
CURRS   = ["Indian Rupee", "Indian Rupee", "Indian Rupee", "USD", "EUR"]

rng = np.random.default_rng(42)
_tid = [0]

def _ts(base, delta_hours=0, jitter_minutes=0):
    return (base + timedelta(hours=delta_hours,
                             minutes=int(rng.integers(0, jitter_minutes+1))
                            )).strftime("%Y/%m/%d %H:%M")

def _row(src, dst, amount_inr, ts, channel="NEFT", is_launder=0):
    """Build one IBM-AML format row in INR (payment currency = Indian Rupee)."""
    _tid[0] += 1
    return {
        "Timestamp": ts,
        "From Bank": rng.choice(BANKS),
        "Account": src,
        "To Bank": rng.choice(BANKS),
        "Account.1": dst,
        "Amount Received": round(amount_inr, 2),
        "Receiving Currency": "Indian Rupee",
        "Amount Paid": round(amount_inr, 2),
        "Payment Currency": "Indian Rupee",
        "Payment Format": channel,
        "Is Laundering": is_launder,
    }

def _norm_rows(accounts, base, n=300, lo=10_000, hi=500_000):
    rows = []
    accs = list(accounts)
    for _ in range(n):
        src = str(rng.choice(accs))
        dst = str(rng.choice(accs))
        if src == dst:
            dst = str(rng.choice(accs))
        amt = float(rng.uniform(lo, hi))
        rows.append(_row(src, dst, amt, _ts(base, int(rng.integers(0, 240)), 30)))
    return rows


class SyntheticDataset:
    """
    Three-day synthetic dataset with embedded fraud patterns and known ground truth.

    Day 1 — initial load:
      • 400 clean "shared" accounts doing normal transactions
      •  10 layering chains (5 hops, 60-minute window, 12% decay)
      •  10 round-trip pairs (≥85% return ratio)
      •  10 structuring accounts (3-5 txns each, ₹900k-₹999k range)
      •   5 dormant accounts (single old txn, no burst yet)
      •  15 peer accounts + 1 income-mismatch account

    Day 2 — incremental (400 returning + 200 new):
      • All shared accounts return with normal activity
      •  5 new structuring accounts (brand-new, never seen before)
      •  The 5 dormant accounts from Day 1 burst with 25 txns each
      •  10 new round-trip pairs among 200 new accounts

    Day 3 — incremental (400 returning + 100 new):
      • 5 previously clean shared accounts start layering (behavioural shift)
      •  100 brand-new accounts (clean)
      •  Layering chains from Day 1 continue (same accounts)
    """

    def __init__(self):
        # shared across all days
        self.shared_accs   = [f"SH_{i:04d}" for i in range(400)]
        # pattern accounts — Day 1
        self.lay_chains    = [[f"LAY{c}_{i}" for i in range(6)] for c in range(10)]
        self.rt_pairs      = [(f"RT_A{i}", f"RT_B{i}") for i in range(10)]
        self.struct_accs   = [f"STRUCT_{i}" for i in range(10)]
        self.dormant_accs  = [f"DORM_{i}" for i in range(5)]
        self.peer_accs     = [f"PEER_{i}" for i in range(15)]
        self.mismatch_acc  = "MISMATCH_0"
        # new on Day 2
        self.new_d2        = [f"NEW2_{i:03d}" for i in range(200)]
        self.struct_d2     = [f"STRUCT2_{i}" for i in range(5)]
        self.rt_pairs_d2   = [(f"RT2_A{i}", f"RT2_B{i}") for i in range(10)]
        # new on Day 3
        self.new_d3        = [f"NEW3_{i:03d}" for i in range(100)]
        self.shift_accs    = self.shared_accs[:5]   # clean→dirty behavioural shift

        # all-account sets per day (for continuation stats)
        self.day1_account_set = (
            set(self.shared_accs) |
            {a for chain in self.lay_chains for a in chain} |
            {a for p in self.rt_pairs for a in p} |
            set(self.struct_accs) | set(self.dormant_accs) |
            set(self.peer_accs) | {self.mismatch_acc}
        )
        self.day2_account_set = (
            self.day1_account_set |
            set(self.new_d2) | set(self.struct_d2) |
            {a for p in self.rt_pairs_d2 for a in p}
        )
        self.day3_account_set = self.day2_account_set | set(self.new_d3)

        # known fraud accounts by type (for recall computation)
        self.known_fraud = {
            "layering":         set(a for chain in self.lay_chains for a in chain),
            "round_trip":       set(a for p in self.rt_pairs for a in p),
            "structuring":      set(self.struct_accs),
            "dormancy":         set(self.dormant_accs),
            "profile_mismatch": {self.mismatch_acc},
        }

    # ── builders ────────────────────────────────────────────────────────────

    def _layering_rows(self, base, chains=None, n_reps=5):
        rows = []
        for chain in (chains or self.lay_chains):
            for rep in range(n_reps):
                start = base + timedelta(hours=rep * 4)
                amt = 600_000.0
                for j in range(len(chain) - 1):
                    ts = _ts(start, 0, j * 8)
                    decay_amt = round(amt * (0.88 ** j), 2)
                    rows.append(_row(chain[j], chain[j+1], decay_amt, ts, "Wire", 1))
        return rows

    def _round_trip_rows(self, base, pairs=None):
        rows = []
        for a, b in (pairs or self.rt_pairs):
            fwd = float(rng.uniform(400_000, 600_000))
            back = round(fwd * 0.92, 2)
            for rep in range(6):
                ts_fwd  = _ts(base, rep * 8,     15)
                ts_back = _ts(base, rep * 8 + 4, 15)
                rows.append(_row(a, b, fwd,  ts_fwd,  "RTGS", 1))
                rows.append(_row(b, a, back, ts_back, "RTGS", 1))
        return rows

    def _structuring_rows(self, base, accs=None):
        rows = []
        normal_dst = self.shared_accs[:20]
        for acc in (accs or self.struct_accs):
            for i in range(4):
                amt = float(rng.uniform(910_000, 995_000))
                ts  = _ts(base, i * 3, 30)
                dst = str(rng.choice(normal_dst))
                rows.append(_row(acc, dst, amt, ts, "NEFT", 1))
        return rows

    def _dormancy_old_rows(self, base):
        rows = []
        for acc in self.dormant_accs:
            rows.append(_row(acc, self.shared_accs[0], 5_000, _ts(base, 0, 30), "NEFT", 0))
            rows.append(_row(acc, self.shared_accs[1], 4_500, _ts(base, 48, 30), "NEFT", 0))
        return rows

    def _dormancy_burst_rows(self, base):
        rows = []
        targets = self.shared_accs[50:75]   # distinct targets, not overlapping old txn targets
        for acc in self.dormant_accs:
            for i in range(25):
                dst = str(rng.choice(targets))
                rows.append(_row(acc, dst, 80_000, _ts(base, i, 5), "IMPS", 1))
        return rows

    def _profile_rows(self, base):
        rows = []
        # 15 peers: low-income salaried, small volumes
        for i, acc in enumerate(self.peer_accs):
            for j in range(5):
                dst = self.peer_accs[(i + 1) % len(self.peer_accs)]
                rows.append(_row(acc, dst, 20_000, _ts(base, j * 24, 60), "UPI", 0))
        # Mismatch: 50 × ₹300k = ₹15M vs declared ₹300k income
        for k in range(50):
            dst = self.peer_accs[k % len(self.peer_accs)]
            rows.append(_row(self.mismatch_acc, dst, 300_000,
                             _ts(base, k * 12, 30), "Wire", 1))
        return rows

    def build_day1(self):
        base = datetime(2025, 6, 1, 8, 0, 0)
        all_accs = list(self.day1_account_set)
        rows = []
        rows += _norm_rows(self.shared_accs, base, n=600)
        rows += self._layering_rows(base)
        rows += self._round_trip_rows(base)
        rows += self._structuring_rows(base)
        rows += self._dormancy_old_rows(base)
        rows += self._profile_rows(base)
        return pd.DataFrame(rows)

    def build_day2(self):
        base = datetime(2026, 3, 1, 8, 0, 0)  # 9 months later → dormancy gap > 180 days
        rows = []
        # Returning shared accounts (normal)
        rows += _norm_rows(self.shared_accs, base, n=400)
        # Dormant burst (the key cross-day pattern)
        rows += self._dormancy_burst_rows(base)
        # New structuring accounts
        rows += self._structuring_rows(base, accs=self.struct_d2)
        # New round-trip accounts
        rows += self._round_trip_rows(base, pairs=self.rt_pairs_d2)
        # New accounts — clean
        rows += _norm_rows(self.new_d2, base, n=300)
        return pd.DataFrame(rows)

    def build_day3(self):
        base = datetime(2026, 6, 1, 8, 0, 0)
        rows = []
        # Returning shared accounts (normal)
        rows += _norm_rows(self.shared_accs, base, n=400)
        # Behavioural shift: 5 clean→dirty accounts now doing layering
        rows += self._layering_rows(base, chains=[[s] + list(self.lay_chains[0][1:])
                                                   for s in self.shift_accs], n_reps=3)
        # Original layering chains continue
        rows += self._layering_rows(base, n_reps=3)
        # New day 3 accounts (clean)
        rows += _norm_rows(self.new_d3, base, n=200)
        return pd.DataFrame(rows)

    def accounts_df_for(self, txn_df):
        """Build accounts DataFrame from transaction participants."""
        all_accs = set(txn_df["Account"]) | set(txn_df["Account.1"])
        rows = []
        for acc in all_accs:
            occ = "salaried"
            inc = 300_000.0
            brk = "low"
            if acc in self.peer_accs or acc == self.mismatch_acc:
                occ, inc, brk = "salaried", 300_000.0, "low"
            rows.append({
                "account_id": acc,
                "account_type": "savings",
                "branch_city": "Mumbai",
                "occupation": occ,
                "income_bracket": brk,
                "declared_annual_income": inc,
                "is_new": True,
            })
        return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# Metrics helpers
# ─────────────────────────────────────────────────────────────────────────────

def recall_for_pattern(detection_results, pattern_key, known_set):
    results = detection_results.get(pattern_key, [])
    flagged = set()
    for r in results:
        flagged.update(r.account_ids)
    if not known_set:
        return None, flagged
    return len(flagged & known_set) / len(known_set), flagged

def score_separation(risk_scores, fraud_accs):
    fraud_s  = [s for a, s in risk_scores.items() if a in fraud_accs]
    clean_s  = [s for a, s in risk_scores.items() if a not in fraud_accs]
    if not fraud_s or not clean_s:
        return None, None, None
    return np.mean(fraud_s), np.mean(clean_s), np.mean(fraud_s) - np.mean(clean_s)

def score_pct(risk_scores, level):
    thresholds = {"LOW": (0, 25), "MEDIUM": (25, 50), "HIGH": (50, 75), "CRITICAL": (75, 100)}
    lo, hi = thresholds[level]
    total = len(risk_scores)
    count = sum(1 for s in risk_scores.values() if lo <= s < hi)
    return count, round(100 * count / max(total, 1), 1)


def xgb_metrics(det_svc):
    m = det_svc.fraud_metrics
    if not m:
        return None
    return m


def anomaly_separation(anomaly_results, fraud_accs):
    df = anomaly_results.set_index("account_id") if "account_id" in anomaly_results.columns else anomaly_results
    fraud_s = [df.loc[a, "anomaly_score"] for a in fraud_accs if a in df.index]
    clean_s = [df.loc[a, "anomaly_score"] for a in df.index if a not in fraud_accs]
    if not fraud_s or not clean_s:
        return None, None
    return np.mean(fraud_s), np.mean(clean_s)


def account_continuation(prev_set, curr_set):
    returning = prev_set & curr_set
    new_acc   = curr_set - prev_set
    left      = prev_set - curr_set
    return returning, new_acc, left


# ─────────────────────────────────────────────────────────────────────────────
# Single-day runner
# ─────────────────────────────────────────────────────────────────────────────

def run_day(day_label, txn_csv_df, accs_df, det_svc_prev=None):
    """
    Ingest one day's IBM-AML CSV, run full pipeline, return results dict.
    If det_svc_prev is given it means this is incremental (reuse trained models).
    """
    t0 = time.time()
    print(f"\n  Running pipeline for {day_label} …", end="", flush=True)

    ingestion = IngestionService()
    accs_norm, txns_norm = ingestion._ibm.parse(txn_csv_df)

    # Merge with pre-built accounts_df (adds occupation / income info)
    accs_norm = accs_norm.merge(
        accs_df[["account_id", "declared_annual_income", "occupation",
                 "income_bracket", "branch_city"]],
        on="account_id", how="left", suffixes=("", "_ext")
    )
    for col in ["declared_annual_income", "occupation", "income_bracket", "branch_city"]:
        ext = col + "_ext"
        if ext in accs_norm.columns:
            accs_norm[col] = accs_norm[col].fillna(accs_norm[ext])
            accs_norm.drop(columns=[ext], inplace=True)
    accs_norm["declared_annual_income"] = accs_norm["declared_annual_income"].fillna(300_000.0)
    accs_norm["occupation"]     = accs_norm["occupation"].fillna("salaried")
    accs_norm["income_bracket"] = accs_norm["income_bracket"].fillna("low")
    accs_norm["branch_city"]    = accs_norm["branch_city"].fillna("Mumbai")

    graph_svc = GraphService()
    graph_svc.build(accs_norm, txns_norm)

    det_svc = DetectionService()
    det_svc.run_full_pipeline(graph_svc, accs_norm, txns_norm)

    elapsed = time.time() - t0
    print(f" done in {elapsed:.1f}s")
    return {
        "accs_df":   accs_norm,
        "txns_df":   txns_norm,
        "graph_svc": graph_svc,
        "det_svc":   det_svc,
        "elapsed":   elapsed,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Existing-file runner  (tracex_test_day*.csv)
# ─────────────────────────────────────────────────────────────────────────────

def run_from_file(label, filepath, accs_df_hint=None):
    t0 = time.time()
    print(f"\n  Running pipeline for {label} ({os.path.basename(filepath)}) …",
          end="", flush=True)
    ingestion = IngestionService()
    accs_norm, txns_norm = ingestion._ibm.parse(filepath)
    if accs_df_hint is not None:
        accs_norm = accs_norm.merge(
            accs_df_hint[["account_id","declared_annual_income","occupation",
                           "income_bracket","branch_city"]],
            on="account_id", how="left", suffixes=("","_h")
        )
        for c in ["declared_annual_income","occupation","income_bracket","branch_city"]:
            h = c+"_h"
            if h in accs_norm.columns:
                accs_norm[c] = accs_norm[c].fillna(accs_norm[h])
                accs_norm.drop(columns=[h], inplace=True)
    accs_norm["declared_annual_income"] = accs_norm.get("declared_annual_income",
                                                         pd.Series(300_000.0)).fillna(300_000.0)
    for c in ["occupation","income_bracket","branch_city"]:
        accs_norm[c] = accs_norm.get(c, pd.Series("salaried")).fillna("salaried")

    graph_svc = GraphService()
    graph_svc.build(accs_norm, txns_norm)
    det_svc = DetectionService()
    det_svc.run_full_pipeline(graph_svc, accs_norm, txns_norm)
    elapsed = time.time() - t0
    print(f" done in {elapsed:.1f}s")
    return {"accs_df": accs_norm, "txns_df": txns_norm,
            "graph_svc": graph_svc, "det_svc": det_svc, "elapsed": elapsed}


# ─────────────────────────────────────────────────────────────────────────────
# Report helpers
# ─────────────────────────────────────────────────────────────────────────────

def print_pattern_table(day_label, det_svc, known_fraud_by_type):
    print(f"\n  Pattern Detection Recall — {day_label}")
    print(f"  {'Pattern':<20} {'Known':>6} {'Flagged':>8} {'Overlap':>8} {'Recall':>8} {'Status'}")
    print(f"  {'-'*20} {'-'*6} {'-'*8} {'-'*8} {'-'*8} {'-'*10}")
    all_recall = []
    for pat, known_set in known_fraud_by_type.items():
        recall, flagged = recall_for_pattern(det_svc.detection_results, pat, known_set)
        overlap = len(flagged & known_set)
        rec_str = f"{recall*100:.0f}%" if recall is not None else "N/A"
        status = (_pass("") if recall is not None and recall >= 0.8
                  else _warn("") if recall is not None and recall >= 0.5
                  else _fail("") if recall is not None
                  else "N/A")
        print(f"  {pat:<20} {len(known_set):>6} {len(flagged):>8} {overlap:>8} {rec_str:>8}   {status}")
        if recall is not None:
            all_recall.append(recall)
    if all_recall:
        avg = np.mean(all_recall)
        print(f"  {'AVERAGE':<20} {'':>6} {'':>8} {'':>8} {avg*100:.0f}%{' ':>4}   "
              + (_pass("") if avg >= 0.7 else _warn("") if avg >= 0.5 else _fail("")))


def print_ml_metrics(day_label, det_svc, known_all_fraud):
    print(f"\n  ML Metrics — {day_label}")

    # Anomaly (IF)
    if det_svc.anomaly_results is not None and len(det_svc.anomaly_results) > 0:
        fraud_avg, clean_avg = anomaly_separation(det_svc.anomaly_results, known_all_fraud)
        n_anom = int(det_svc.anomaly_results["is_anomaly"].sum())
        n_total = len(det_svc.anomaly_results)
        anom_rate = n_anom / max(n_total, 1)
        fa_str = f"{fraud_avg:.1f}" if fraud_avg is not None else "N/A"
        ca_str = f"{clean_avg:.1f}" if clean_avg is not None else "N/A"
        sep_ok = fraud_avg is not None and clean_avg is not None and fraud_avg > clean_avg
        print(f"  Isolation Forest  anomaly rate={anom_rate*100:.1f}%  "
              f"fraud_avg={fa_str}  clean_avg={ca_str}  "
              + (_pass("fraud scores higher") if sep_ok else _warn("no clear separation")))
    else:
        print(_warn("  Isolation Forest results missing"))

    # XGBoost
    m = xgb_metrics(det_svc)
    if m:
        auc    = m.get("auc_roc", 0)
        f1     = m.get("f1", 0)
        prec   = m.get("precision", 0)
        rec    = m.get("recall", 0)
        pr_auc = m.get("pr_auc", 0)
        thresh = m.get("threshold", 0)
        n_test_pos = m.get("n_test_positives", 0)
        print(f"  XGBoost           AUC-ROC={auc:.3f}  PR-AUC={pr_auc:.3f}  "
              f"F1={f1:.3f}  P={prec:.3f}  R={rec:.3f}  "
              f"thresh={thresh:.3f}  test_pos={n_test_pos}")
        print("  " + (_pass("AUC-ROC ≥ 0.85") if auc >= 0.85
                      else _warn("AUC-ROC 0.7–0.85") if auc >= 0.7
                      else _fail("AUC-ROC < 0.70")))
    else:
        print(_warn("  XGBoost skipped (insufficient labels or training data)"))


def print_risk_distribution(day_label, risk_scores, known_all_fraud):
    print(f"\n  Risk Score Distribution — {day_label}")
    lvls = [("CRITICAL", 75, 100), ("HIGH", 50, 75), ("MEDIUM", 25, 50), ("LOW", 0, 25)]
    for name, lo, hi in lvls:
        cnt  = sum(1 for s in risk_scores.values() if lo <= s < hi)
        pct  = 100 * cnt / max(len(risk_scores), 1)
        bar  = "█" * int(pct / 2)
        print(f"  {name:<10} {cnt:>5} ({pct:5.1f}%)  {bar}")

    fa, ca, sep = score_separation(risk_scores, known_all_fraud)
    if fa is not None:
        print(f"  Fraud mean={fa:.1f}  Clean mean={ca:.1f}  Gap={sep:.1f}  "
              + (_pass("good separation") if sep >= 10
                 else _warn("moderate separation") if sep >= 5
                 else _fail("poor separation")))


def print_role_table(det_svc):
    role_counts = defaultdict(int)
    for r in det_svc.roles.values():
        role_counts[r["role"]] += 1
    total = sum(role_counts.values())
    print(f"  {'Role':<12} {'Count':>7} {'Pct':>7}")
    print(f"  {'-'*12} {'-'*7} {'-'*7}")
    for role in ["SOURCE", "MULE", "SINK", "NORMAL"]:
        cnt = role_counts.get(role, 0)
        print(f"  {role:<12} {cnt:>7} {100*cnt/max(total,1):>6.1f}%")


def print_graph_stats(graph_svc, day_label):
    G = graph_svc.graph.G
    n_nodes = G.number_of_nodes()
    n_edges = G.number_of_edges()
    centrality = graph_svc.graph.compute_centrality()
    pr_vals  = list(centrality["pagerank"].values())
    bc_vals  = list(centrality["betweenness"].values())
    print(f"\n  Graph Stats — {day_label}")
    print(f"  Nodes={n_nodes:,}  Edges={n_edges:,}  "
          f"Density={n_edges/max(n_nodes*(n_nodes-1),1):.5f}")
    print(f"  PageRank   max={max(pr_vals):.5f}  mean={np.mean(pr_vals):.5f}  "
          + (_pass("sums to ~1") if abs(sum(pr_vals)-1.0)<0.01 else _warn("sum≠1")))
    print(f"  Betweenness max={max(bc_vals):.4f}  mean={np.mean(bc_vals):.4f}")


def print_account_continuation(prev_set, curr_set, day_label, prev_label):
    ret, new, left = account_continuation(prev_set, curr_set)
    print(f"\n  Account Continuation: {prev_label} → {day_label}")
    print(f"  {'Returning (seen before)':<30} {len(ret):>6}  "
          + (_pass("") if len(ret) > 0 else _warn("no returning accounts")))
    print(f"  {'Brand-new (first appearance)':<30} {len(new):>6}")
    print(f"  {'Dropped (left after prev day)':<30} {len(left):>6}")
    print(f"  {'Total accounts this day':<30} {len(curr_set):>6}")
    print(f"  Retention rate: {100*len(ret)/max(len(prev_set),1):.1f}%")


def print_feature_qa(det_svc, day_label):
    f = det_svc.features_df
    print(f"\n  Feature QA — {day_label}")
    print(f"  Shape: {f.shape[0]} accounts × {f.shape[1]} features  "
          + (_pass("29 features") if f.shape[1] == 29 else _warn(f"expected 29, got {f.shape[1]}")))
    nan_cols = f.columns[f.isna().any()].tolist()
    print(f"  NaN columns: {nan_cols if nan_cols else 'none'}  "
          + (_pass("") if not nan_cols else _fail(f"{len(nan_cols)} columns have NaN")))
    inf_cols = f.columns[np.isinf(f.values).any(axis=0)].tolist()
    print(f"  Inf columns: {inf_cols if inf_cols else 'none'}  "
          + (_pass("") if not inf_cols else _fail(f"{len(inf_cols)} columns have Inf")))
    # Known stubs
    stub_cols = []
    if (f["geographic_dispersion"] == 0).all():
        stub_cols.append("geographic_dispersion")
    if (f["clustering_coeff"] == 0).all():
        stub_cols.append("clustering_coeff")
    if (f["velocity_10min"] == f["velocity_1hour"]).all():
        stub_cols.append("velocity_10min==velocity_1hour")
    if stub_cols:
        print(f"  {_warn('Stub/duplicate features: ' + ', '.join(stub_cols))}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{W}{'═'*72}{E}")
    print(f"{W}  TRACEX SYSTEM VALIDATION{E}  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{W}{'═'*72}{E}")

    ds = SyntheticDataset()
    all_known_fraud = set().union(*ds.known_fraud.values())

    # ─── SECTION 1: SYNTHETIC DATA ───────────────────────────────────────────
    section("PART A — SYNTHETIC DATA  (known ground truth, 3 incremental days)")

    print("\n  Building synthetic datasets …")
    d1_csv = ds.build_day1()
    d2_csv = ds.build_day2()
    d3_csv = ds.build_day3()

    d1_accs = ds.accounts_df_for(d1_csv)
    d2_accs = ds.accounts_df_for(pd.concat([d1_csv, d2_csv]))
    d3_accs = ds.accounts_df_for(pd.concat([d1_csv, d2_csv, d3_csv]))

    print(f"  Day 1: {len(d1_csv):,} transactions  "
          f"({int(d1_csv['Is Laundering'].sum())} fraud rows  "
          f"{len(set(d1_csv['Account'])|set(d1_csv['Account.1'])):,} accounts)")
    print(f"  Day 2: {len(d2_csv):,} transactions  "
          f"({int(d2_csv['Is Laundering'].sum())} fraud rows  "
          f"{len(set(d2_csv['Account'])|set(d2_csv['Account.1'])):,} accounts)")
    print(f"  Day 3: {len(d3_csv):,} transactions  "
          f"({int(d3_csv['Is Laundering'].sum())} fraud rows  "
          f"{len(set(d3_csv['Account'])|set(d3_csv['Account.1'])):,} accounts)")

    print("\n  Known fraud accounts by pattern:")
    for pat, s in ds.known_fraud.items():
        print(f"    {pat:<20} {len(s):>4} accounts")

    # ── Day 1 ────────────────────────────────────────────────────────────────
    section("SYNTHETIC — DAY 1  (initial load, all patterns planted)")
    r1 = run_day("Day 1", d1_csv, d1_accs)
    det1 = r1["det_svc"]

    d1_acc_set = set(r1["accs_df"]["account_id"])
    print_graph_stats(r1["graph_svc"], "Day 1")
    print_feature_qa(det1, "Day 1")
    print_pattern_table("Day 1", det1, ds.known_fraud)
    print_ml_metrics("Day 1", det1, all_known_fraud)
    print_risk_distribution("Day 1", det1.risk_scores, all_known_fraud)
    print_role_table(det1)

    # ── Day 2 (incremental, combined with Day 1) ──────────────────────────────
    section("SYNTHETIC — DAY 2  (incremental: returning accounts + dormancy burst)")

    # Combined view = Day 1 + Day 2 (simulates /api/refresh after both uploads)
    d12_csv  = pd.concat([d1_csv, d2_csv]).reset_index(drop=True)
    r12 = run_day("Day 1+2 combined", d12_csv, d2_accs)
    det12 = r12["det_svc"]

    d12_acc_set = set(r12["accs_df"]["account_id"])

    print_account_continuation(d1_acc_set, d12_acc_set, "Day 2", "Day 1")

    # Day 2-specific fraud (dormancy, new structuring, new RT)
    d2_known_fraud = {
        "layering":        ds.known_fraud["layering"],
        "round_trip":      ds.known_fraud["round_trip"] | {a for p in ds.rt_pairs_d2 for a in p},
        "structuring":     ds.known_fraud["structuring"] | set(ds.struct_d2),
        "dormancy":        ds.known_fraud["dormancy"],        # NOW detectable (burst happened)
        "profile_mismatch":ds.known_fraud["profile_mismatch"],
    }
    d12_all_fraud = set().union(*d2_known_fraud.values())

    print_graph_stats(r12["graph_svc"], "Day 1+2")
    print_feature_qa(det12, "Day 1+2")
    print_pattern_table("Day 1+2 combined", det12, d2_known_fraud)
    print_ml_metrics("Day 1+2", det12, d12_all_fraud)
    print_risk_distribution("Day 1+2", det12.risk_scores, d12_all_fraud)
    print_role_table(det12)

    # ── Day 3 (combined, behavioural shift) ───────────────────────────────────
    section("SYNTHETIC — DAY 3  (behavioural shift: 5 clean→dirty accounts)")

    d123_csv = pd.concat([d1_csv, d2_csv, d3_csv]).reset_index(drop=True)
    r123 = run_day("Day 1+2+3 combined", d123_csv, d3_accs)
    det123 = r123["det_svc"]

    d123_acc_set = set(r123["accs_df"]["account_id"])

    print_account_continuation(d12_acc_set, d123_acc_set, "Day 3", "Day 2")

    d3_known_fraud = dict(d2_known_fraud)
    d3_known_fraud["layering"] = (d2_known_fraud["layering"] | set(ds.shift_accs))

    d123_all_fraud = set().union(*d3_known_fraud.values())

    print_graph_stats(r123["graph_svc"], "Day 1+2+3")
    print_feature_qa(det123, "Day 1+2+3")
    print_pattern_table("Day 1+2+3", det123, d3_known_fraud)

    # Check specifically if the behavioural-shift accounts got flagged
    shift_lay = det123.detection_results.get("layering", [])
    shift_flagged = {a for r in shift_lay for a in r.account_ids} & set(ds.shift_accs)
    print(f"\n  Behavioural-shift detection (clean→dirty layering):")
    print(f"  Shift accounts: {ds.shift_accs}")
    print(f"  Flagged:        {sorted(shift_flagged) if shift_flagged else '(none)'}")
    print("  " + (_pass(f"{len(shift_flagged)}/{len(ds.shift_accs)} caught")
                  if shift_flagged else _warn("shift accounts not flagged yet (need more txns)")))

    print_ml_metrics("Day 1+2+3", det123, d123_all_fraud)
    print_risk_distribution("Day 1+2+3", det123.risk_scores, d123_all_fraud)
    print_role_table(det123)

    # ─── SECTION 2: EXISTING SYNTHETIC FILES ─────────────────────────────────
    section("PART B — GENERATED SYNTHETIC FILES  (tracex_test_day*.csv)")

    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    files = {
        "Gen-Day1": os.path.join(data_dir, "tracex_test_day1.csv"),
        "Gen-Day2": os.path.join(data_dir, "tracex_test_day2_incremental.csv"),
        "Gen-Day3": os.path.join(data_dir, "tracex_test_day3_demo.csv"),
    }

    gen_results = {}
    gen_acc_sets = {}
    prev_file_label = None

    for label, path in files.items():
        if not os.path.exists(path):
            print(f"  {_warn(label + ' file missing: ' + path)}")
            continue
        r = run_from_file(label, path)
        gen_results[label] = r
        gen_acc_sets[label] = set(r["accs_df"]["account_id"])

    for i, (label, r) in enumerate(gen_results.items()):
        det = r["det_svc"]
        det_keys = list(gen_results.keys())
        if i > 0:
            prev_label = det_keys[i-1]
            print_account_continuation(gen_acc_sets[prev_label], gen_acc_sets[label],
                                       label, prev_label)
        txns = r["txns_df"]
        fraud_accs_file = set(
            txns.loc[txns["is_laundering"]==1,"source_account"].tolist() +
            txns.loc[txns["is_laundering"]==1,"dest_account"].tolist()
        )
        print(f"\n  {label}: {len(txns):,} txns  "
              f"{int(txns['is_laundering'].sum())} fraud rows  "
              f"{len(fraud_accs_file)} labeled fraud accounts")
        print_pattern_table(label, det, {
            "layering": fraud_accs_file, "round_trip": fraud_accs_file,
            "structuring": fraud_accs_file, "dormancy": fraud_accs_file,
            "profile_mismatch": fraud_accs_file,
        })
        print_ml_metrics(label, det, fraud_accs_file)
        print_risk_distribution(label, det.risk_scores, fraud_accs_file)
        # Top 10 flagged accounts
        top10 = sorted(det.risk_scores.items(), key=lambda x: x[1], reverse=True)[:10]
        print(f"\n  Top-10 Risk Accounts — {label}")
        for rank, (acc, score) in enumerate(top10, 1):
            is_fraud = "🔴" if acc in fraud_accs_file else "⚪"
            role = det.roles.get(acc, {}).get("role", "?")
            print(f"  {rank:>2}. {acc:<20} score={score:>6.1f}  role={role:<8} {is_fraud}")

    # ─── SECTION 3: SUMMARY TABLE ─────────────────────────────────────────────
    section("VALIDATION SUMMARY")

    rows_summary = []
    for day_label, r, kf in [
        ("Synthetic Day 1",     r1,   all_known_fraud),
        ("Synthetic Day 1+2",   r12,  d12_all_fraud),
        ("Synthetic Day 1+2+3", r123, d123_all_fraud),
    ] + [
        (lbl, res, set(
            res["txns_df"].loc[res["txns_df"]["is_laundering"]==1,"source_account"].tolist() +
            res["txns_df"].loc[res["txns_df"]["is_laundering"]==1,"dest_account"].tolist()
        ))
        for lbl, res in gen_results.items()
    ]:
        det = r["det_svc"]
        fa, ca, sep = score_separation(det.risk_scores, kf)
        m = xgb_metrics(det)
        auc = m.get("auc_roc", 0) if m else 0
        f1  = m.get("f1", 0) if m else 0
        total_det = sum(len(v) for v in det.detection_results.values())
        rows_summary.append((day_label, len(r["accs_df"]), len(r["txns_df"]),
                              total_det, f"{fa:.1f}" if fa else "N/A",
                              f"{ca:.1f}" if ca else "N/A",
                              f"{sep:.1f}" if sep else "N/A",
                              f"{auc:.3f}" if auc else "N/A",
                              f"{f1:.3f}"  if f1  else "N/A"))

    hdr = (f"  {'Dataset':<22} {'Accs':>6} {'Txns':>7} {'Detns':>6} "
           f"{'FraudRisk':>9} {'CleanRisk':>9} {'Gap':>6} {'AUC':>7} {'F1':>7}")
    print(hdr)
    print("  " + "-" * len(hdr.rstrip()))
    for row in rows_summary:
        print(f"  {row[0]:<22} {row[1]:>6,} {row[2]:>7,} {row[3]:>6} "
              f"{row[4]:>9} {row[5]:>9} {row[6]:>6} {row[7]:>7} {row[8]:>7}")

    # ─── SECTION 4: BUG TRACKER ───────────────────────────────────────────────
    section("CONFIRMED BUGS IMPACTING RESULTS")
    bugs = [
        ("BUG-001", "CRITICAL", "temporal_bfs (Fund Trail) broken — timestamps missing from graph edges"),
        ("BUG-002", "MEDIUM",   "velocity_10min == velocity_1hour (both = max_daily_txn_count)"),
        ("BUG-003", "MEDIUM",   "geographic_dispersion always 0.0 (hardcoded stub)"),
        ("BUG-004", "LOW",      "clustering_coeff always 0.0 (hardcoded stub)"),
        ("BUG-005", "HIGH",     "EvidencePack.json_data→AttributeError→/api/evidence returns {}"),
        ("BUG-006", "LOW",      "nvidia-smi at import time — noisy error on Mac (non-fatal)"),
        ("BUG-007", "CRITICAL", "tests/test_core.py 100% broken (imports from core.* which doesn't exist)"),
        ("BUG-008", "MEDIUM",   "generate_test_pair.py Day 3 structuring amounts may escape ₹9L band"),
        ("BUG-009", "LOW",      "channel_entropy ≠ Shannon entropy (wrong formula)"),
        ("BUG-010", "HIGH",     "/api/anomaly is O(N²) — calls _build_flags per account in loop"),
        ("BUG-011", "CRITICAL", "dormancy.py:67 — wrong index used post-filter (FIXED in this session)"),
        ("BUG-012", "HIGH",     "dormancy.py:78 — off-by-one split_row (FIXED in this session)"),
    ]
    for bid, sev, desc in bugs:
        col = R if sev == "CRITICAL" else Y if sev in ("HIGH","MEDIUM") else B
        fixed = " ← FIXED" if "FIXED" in desc else ""
        print(f"  {col}{bid}  [{sev}]{E}  {desc}{G}{fixed}{E}")

    print(f"\n{W}{'═'*72}{E}")
    print(f"{W}  VALIDATION COMPLETE{E}")
    print(f"{W}{'═'*72}{E}\n")


if __name__ == "__main__":
    main()
