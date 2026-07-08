"""
Evidence Generator — FIU-IND compliant STR evidence packs.

Generates:
- PDF report in STR (Suspicious Transaction Report) format
- JSON payload (machine-readable)
- SHA-256 hash for tamper detection (CP-08)
"""
import hashlib
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from fpdf import FPDF

from infrastructure.health import health
from services.common.constants import SUSPICION_CATEGORIES
from services.common.models import EvidencePack, DetectionSummary

logger = logging.getLogger(__name__)

DETECTION_LABELS = {
    "fan_out": "High-Degree Fund Dispersal (Fan-Out)",
    "fan_in": "Fund Consolidation from Multiple Sources (Fan-In)",
    "layering": "Multi-Hop Fund Layering (Transaction Chain)",
    "round_trip": "Circular Fund Transfer (Round-Trip)",
    "structuring": "Transaction Structuring Below Reporting Threshold",
    "dormancy": "Dormant Account Reactivation with High-Value Activity",
    "profile_mismatch": "Behavioural Profile Anomaly",
    "bipartite": "Multi-Party Coordinated Fund Movement",
    "scatter_gather": "Scatter-Gather Pattern",
    "cycle": "Circular Fund Cycle",
    "velocity_spike": "High-Frequency Transaction Burst",
    "mule_suspect": "Suspected Money Mule (Pass-Through Account)",
}


def _label_detection(det_type: str) -> str:
    return DETECTION_LABELS.get(det_type, det_type.replace("_", " ").title())


def _sanitize(text: str) -> str:
    """Remove or replace characters that break PDF generation."""
    replacements = {
        "₹": "INR ", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "--",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    original_len = len(text)
    encoded = text.encode("latin-1", "ignore").decode("latin-1")
    if len(encoded) < original_len:
        logger.debug("Non-latin-1 characters dropped during PDF sanitization")
    return encoded


def _format_inr(amount: float) -> str:
    if amount >= 1e7:
        return f"INR {amount / 1e7:.2f} Cr"
    if amount >= 1e5:
        return f"INR {amount / 1e5:.2f} L"
    if amount >= 1e3:
        return f"INR {amount / 1e3:.1f} K"
    return f"INR {amount:,.0f}"


class EvidenceGenerator:
    """Generate FIU-IND compliant Suspicious Transaction Report evidence packs."""

    def generate(self, case_id: str, account_ids: List[str],
                 detection_summary: DetectionSummary, transactions_df: pd.DataFrame,
                 accounts_df: pd.DataFrame,
                 case_notes: str = "") -> EvidencePack:
        """Generate complete evidence pack with PDF + JSON + hash."""

        case_data = self._assemble(
            case_id, account_ids, detection_summary,
            transactions_df, accounts_df, case_notes,
        )

        json_payload = json.dumps(case_data, default=str, indent=2)
        json_hash = hashlib.sha256(json_payload.encode()).hexdigest()

        pdf_bytes = self._build_pdf(case_data)

        pack = EvidencePack(
            case_id=case_id,
            str_reference=f"STR-{datetime.now().strftime('%Y')}-{case_id}",
            pdf_bytes=pdf_bytes,
            json_payload=json_payload,
            json_hash=json_hash,
        )

        # CP-08: store hash for integrity verification
        health.increment("evidence_generated")
        logger.info("Evidence pack generated: %s (hash: %s...)", case_id, json_hash[:16])

        return pack

    def _assemble(self, case_id, account_ids, detection_summary: DetectionSummary,
                  transactions_df, accounts_df, case_notes) -> Dict:
        risk_scores = detection_summary.risk_scores
        detection_results = detection_summary.detection_results

        relevant_txns = transactions_df[
            transactions_df["source_account"].isin(account_ids) |
            transactions_df["dest_account"].isin(account_ids)
        ].sort_values("timestamp")

        account_details = []
        for acc_id in account_ids:
            row = accounts_df[accounts_df["account_id"] == acc_id]
            if len(row) > 0:
                d = row.iloc[0].to_dict()
                d["risk_score"] = risk_scores.get(acc_id, 0)
                account_details.append(d)

        categories = self._determine_categories(detection_results, account_ids)
        total_amount = float(relevant_txns["amount"].sum())
        max_risk = max([risk_scores.get(a, 0) for a in account_ids], default=0)

        return {
            "case_id": case_id,
            "str_reference": f"STR-{datetime.now().strftime('%Y')}-{case_id}",
            "generated_at": datetime.now().isoformat(),
            "reporting_entity": {
                "name": "Public Sector Bank",
                "category": "Scheduled Commercial Bank",
                "report_type": "Suspicious Transaction Report (STR)",
            },
            "accounts": account_details,
            "transactions": relevant_txns.head(50).to_dict("records"),
            "total_transactions": len(relevant_txns),
            "total_amount": total_amount,
            "max_risk_score": max_risk,
            "categories": categories,
            "case_notes": case_notes,
            "detection_summary": {
                _label_detection(dt): len([d for d in dets if any(a in account_ids for a in d.account_ids)])
                for dt, dets in detection_results.items()
            } if isinstance(detection_results, dict) else {},
        }

    def _determine_categories(self, detection_results, account_ids) -> List[str]:
        categories = set()
        if isinstance(detection_results, dict):
            for det_type, dets in detection_results.items():
                for d in dets:
                    if any(a in account_ids for a in d.account_ids):
                        if det_type == "layering":
                            categories.add(SUSPICION_CATEGORIES[4])
                        elif det_type == "round_trip":
                            categories.add(SUSPICION_CATEGORIES[7])
                        elif det_type == "structuring":
                            categories.add(SUSPICION_CATEGORIES[3])
                        elif det_type == "dormancy":
                            categories.add(SUSPICION_CATEGORIES[6])
                        elif det_type == "profile_mismatch":
                            categories.add(SUSPICION_CATEGORIES[2])
        return list(categories) or [SUSPICION_CATEGORIES[13]]

    def _build_pdf(self, data: Dict) -> bytes:
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Header
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, _sanitize("SUSPICIOUS TRANSACTION REPORT (STR)"),
                 new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _sanitize(f"Reference: {data.get('str_reference', '')}"),
                 new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.cell(0, 6, _sanitize(f"Generated: {data.get('generated_at', '')}"),
                 new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.cell(0, 6, _sanitize("CONFIDENTIAL - FOR LAW ENFORCEMENT USE ONLY"),
                 new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(10)

        # Part A: Reporting Entity
        self._section(pdf, "PART A: REPORTING ENTITY")
        entity = data.get("reporting_entity", {})
        self._field(pdf, "Entity", entity.get("name", ""))
        self._field(pdf, "Category", entity.get("category", ""))
        self._field(pdf, "Report Type", entity.get("report_type", ""))
        self._field(pdf, "Date", datetime.now().strftime("%Y-%m-%d"))
        pdf.ln(5)

        # Part B: Subject Accounts
        self._section(pdf, "PART B: SUBJECT ACCOUNTS")
        for acc in data.get("accounts", []):
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, _sanitize(f"Account: {acc.get('account_id', '')}"),
                     new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            self._field(pdf, "  Type", str(acc.get("account_type", "")))
            self._field(pdf, "  Branch", str(acc.get("branch_city", "")))
            self._field(pdf, "  Occupation", str(acc.get("occupation", "")))
            self._field(pdf, "  Declared Income", _format_inr(acc.get("declared_annual_income", 0)))
            self._field(pdf, "  Risk Score", f"{acc.get('risk_score', 0):.1f}/100")
            pdf.ln(3)
        pdf.ln(5)

        # Part C: Transaction Summary
        self._section(pdf, "PART C: TRANSACTION SUMMARY")
        self._field(pdf, "Total Transactions", str(data.get("total_transactions", 0)))
        self._field(pdf, "Total Amount", _format_inr(data.get("total_amount", 0)))
        self._field(pdf, "Max Risk Score", f"{data.get('max_risk_score', 0):.1f}/100")

        # Transaction table (top 20)
        txns = data.get("transactions", [])[:20]
        if txns:
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 8)
            widths = [25, 25, 25, 25, 20, 20]
            headers = ["Date", "From", "To", "Amount", "Channel", "Type"]
            for w, h in zip(widths, headers):
                pdf.cell(w, 6, h, border=1)
            pdf.ln()
            pdf.set_font("Helvetica", "", 7)
            for t in txns:
                def _abbrev_acc(a: str) -> str:
                    return f"...{a[-6:]}" if len(a) > 10 else a
                vals = [
                    str(t.get("timestamp", ""))[:10],
                    _abbrev_acc(str(t.get("source_account", ""))),
                    _abbrev_acc(str(t.get("dest_account", ""))),
                    _format_inr(t.get("amount", 0)),
                    str(t.get("channel", ""))[:8],
                    str(t.get("txn_type", ""))[:8],
                ]
                for w, v in zip(widths, vals):
                    pdf.cell(w, 5, _sanitize(v), border=1)
                pdf.ln()
        pdf.ln(5)

        # Part D: Suspicion
        self._section(pdf, "PART D: REASON FOR SUSPICION")
        self._field(pdf, "Categories", ", ".join(data.get("categories", ["Other"])))
        pdf.ln(2)
        if data.get("case_notes"):
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, _sanitize(data["case_notes"]))
        else:
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, _sanitize(
                "Automated detection by TraceX. Multiple independent indicators "
                "identified through graph analysis, ML anomaly detection, and pattern recognition."
            ))

        # Detection summary
        det = data.get("detection_summary", {})
        if det:
            pdf.ln(3)
            self._section(pdf, "DETECTION SUMMARY")
            for dtype, count in det.items():
                if count > 0:
                    self._field(pdf, f"  {_label_detection(dtype)}", f"{count} instance(s)")

        # Footer
        pdf.ln(10)
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(0, 6, _sanitize("Generated by TraceX AML Intelligence System - Confidential"),
                 new_x="LMARGIN", new_y="NEXT")

        return pdf.output()

    @staticmethod
    def _section(pdf: FPDF, title: str):
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, _sanitize(title), new_x="LMARGIN", new_y="NEXT")

    @staticmethod
    def _field(pdf: FPDF, label: str, value: str):
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, _sanitize(f"{label}: {value}"), new_x="LMARGIN", new_y="NEXT")
