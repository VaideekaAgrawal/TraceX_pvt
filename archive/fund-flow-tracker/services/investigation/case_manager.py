"""
Case Manager — investigation lifecycle management.

Case states: OPEN → INVESTIGATING → ESCALATED → CLOSED_TP / CLOSED_FP
Resolution feeds back into labelled dataset for model retraining.
"""
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from infrastructure.database import get_database
from services.common.models import Alert, Case, CaseStatus, Priority, make_deterministic_alert_id

logger = logging.getLogger(__name__)


class CaseManager:
    """Manages the lifecycle of investigation cases.

    Alerts are DB-backed (infrastructure/database.py `alerts` table) so
    they survive a server restart instead of living only in an in-process
    dict that got wiped on every pipeline re-run. Cases remain in-memory
    for now — unifying them with the separate DB-backed `cases` table used
    by the /api/cases routes is a known follow-up, out of scope here.
    """

    def __init__(self):
        self._cases: Dict[str, Case] = {}

    @property
    def db(self):
        return get_database()

    @staticmethod
    def _row_to_alert(row: Dict) -> Alert:
        return Alert(
            alert_id=row["alert_id"],
            account_ids=row.get("account_ids") or ([row["account_id"]] if row.get("account_id") else []),
            detection_type=row.get("pattern_type", ""),
            score=row.get("risk_score", 0.0) or 0.0,
            severity=row.get("severity", "MEDIUM"),
            created_at=row.get("detected_at") or row.get("created_at", ""),
            status=row.get("status", "open"),
            assigned_to=row.get("assigned_to", ""),
            notes=row.get("notes", ""),
        )

    # ── Alerts ────────────────────────────────────────────────────────

    def create_alert(self, account_ids: List[str], detection_type: str,
                     score: float, severity: str, date_str: Optional[str] = None) -> Alert:
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        alert_id = make_deterministic_alert_id(account_ids, detection_type, date_str)
        self.db.upsert_alert({
            "alert_id": alert_id,
            "account_ids": account_ids,
            "pattern_type": detection_type,
            "risk_score": score,
            "risk_level": severity,
            "severity": severity,
            "status": "open",
            "source": "pipeline",
        })
        logger.info("Alert created: %s (%s, score=%.2f)", alert_id, detection_type, score)
        return self._row_to_alert(self.db.get_alert(alert_id))

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        row = self.db.get_alert(alert_id)
        return self._row_to_alert(row) if row else None

    def list_alerts(self, status: Optional[str] = None) -> List[Alert]:
        rows = self.db.get_alerts(status=status, limit=1000)
        alerts = [self._row_to_alert(r) for r in rows]
        return sorted(alerts, key=lambda a: a.score, reverse=True)

    # ── Cases ─────────────────────────────────────────────────────────

    def create_case(self, account_ids: List[str], typology: str,
                    priority: str = Priority.P3.value,
                    alert_ids: Optional[List[str]] = None,
                    notes: str = "") -> Case:
        case_id = f"CASE-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        case = Case(
            case_id=case_id,
            alert_ids=alert_ids or [],
            account_ids=account_ids,
            priority=priority,
            typology=typology,
            notes=notes,
        )
        self._cases[case_id] = case

        # Link alerts to case
        for aid in case.alert_ids:
            row = self.db.get_alert(aid)
            if row:
                row["status"] = "assigned"
                self.db.upsert_alert(row)

        logger.info("Case created: %s (typology=%s, priority=%s)", case_id, typology, priority)
        return case

    def update_case_status(self, case_id: str, new_status: str,
                           notes: str = "") -> Optional[Case]:
        case = self._cases.get(case_id)
        if not case:
            return None
        case.status = new_status
        case.updated_at = datetime.utcnow().isoformat()
        if notes:
            case.notes += f"\n[{case.updated_at}] {notes}"
        logger.info("Case %s status → %s", case_id, new_status)
        return case

    def resolve_case(self, case_id: str, resolution: str,
                     is_true_positive: bool) -> Optional[Case]:
        """
        Resolve a case. The resolution feeds back into the labelled dataset
        for model retraining (feedback loop).
        """
        case = self._cases.get(case_id)
        if not case:
            return None
        case.status = CaseStatus.CLOSED_TRUE_POSITIVE.value if is_true_positive else CaseStatus.CLOSED_FALSE_POSITIVE.value
        case.resolution = resolution
        case.updated_at = datetime.utcnow().isoformat()
        logger.info("Case %s resolved: %s (TP=%s)", case_id, resolution, is_true_positive)
        return case

    def get_case(self, case_id: str) -> Optional[Case]:
        return self._cases.get(case_id)

    def list_cases(self, status: Optional[str] = None) -> List[Case]:
        cases = list(self._cases.values())
        if status:
            cases = [c for c in cases if c.status == status]
        return sorted(cases, key=lambda c: c.created_at, reverse=True)

    def get_stats(self) -> Dict[str, int]:
        return {
            "total_alerts": len(self.db.get_alerts(limit=100000)),
            "total_cases": len(self._cases),
            "open_cases": sum(1 for c in self._cases.values() if c.status == CaseStatus.OPEN.value),
            "investigating": sum(1 for c in self._cases.values() if c.status == CaseStatus.INVESTIGATING.value),
            "escalated": sum(1 for c in self._cases.values() if c.status == CaseStatus.ESCALATED.value),
            "closed_tp": sum(1 for c in self._cases.values() if c.status == CaseStatus.CLOSED_TRUE_POSITIVE.value),
            "closed_fp": sum(1 for c in self._cases.values() if c.status == CaseStatus.CLOSED_FALSE_POSITIVE.value),
        }

    def auto_create_alerts_from_detections(self, detection_results: Dict,
                                            date_str: Optional[str] = None) -> Dict[str, List]:
        """Upsert an alert per detection from this pipeline run (capped at the
        top 500 by score) and mark any previously-open alert whose pattern
        didn't re-fire this run as 'stale'. Unlike the old in-memory version,
        this never wipes the alert store first — DB upsert semantics mean an
        alert that re-fires keeps its original `detected_at` and only bumps
        `last_seen_at`, and one that stops firing is closed out rather than
        silently vanishing.

        Returns a diff — alerts / new_ids / reactivated_ids / stale_ids —
        so callers can tell "flagged for the first time today" apart from
        "still active, seen again" (used by the daily run summary)."""
        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        _MAX_ALERTS = 500

        existing_before = {row["alert_id"] for row in self.db.get_alerts(limit=100_000)}

        all_dets = []
        for det_type, results in detection_results.items():
            all_dets.extend(results)
        all_dets.sort(key=lambda d: d.score, reverse=True)

        alerts = []
        current_ids = []
        for det in all_dets[:_MAX_ALERTS]:
            alert = self.create_alert(
                account_ids=det.account_ids,
                detection_type=det.detection_type,
                score=det.score,
                severity=det.severity,
                date_str=date_str,
            )
            alerts.append(alert)
            current_ids.append(alert.alert_id)

        stale_ids = self.db.close_stale_alerts(current_ids)
        new_ids = [aid for aid in current_ids if aid not in existing_before]
        reactivated_ids = [aid for aid in current_ids if aid in existing_before]

        logger.info("Alerts: %d total (%d new, %d reactivated, %d closed stale)",
                    len(alerts), len(new_ids), len(reactivated_ids), len(stale_ids))
        return {
            "alerts": alerts,
            "new_ids": new_ids,
            "reactivated_ids": reactivated_ids,
            "stale_ids": stale_ids,
        }
