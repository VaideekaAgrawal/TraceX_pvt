"""
Alert generation from detection output (ROADMAP Phase 4).

`make_deterministic_alert_id` is ported unchanged from
`archive/fund-flow-tracker/services/common/models.py` -- same (accounts,
detection_type, date) always produces the same `alert_id`, so re-running
detection on the same day refreshes an existing alert (`last_seen_at`
updated, via `AlertRepository.update()`) instead of creating a duplicate
row.

`generate_alerts_from_detection` takes the already-computed ensemble scores
(`EnsembleScorer.compute_all`'s `dict[account_id, float]` composite 0-100
score) and the Rule Engine's grouped detection output (`RuleEngine.run_all`'s
`dict[detection_type, list[DetectionResult]]`) -- reusing both directly
rather than standing up a parallel scoring pipeline (CLAUDE.md's
"reuse before rebuild"). Severity/priority/confidence are derived from the
same `EnsembleScorer` methods the archive used (`compute_priority`,
`compute_confidence`) where the inputs are available from this narrower call
surface; `confidence` calls `compute_confidence` with `anomaly_score`/
`fraud_prob`/`pagerank`/`betweenness` all zeroed (confirmed equivalent to a
hand-rolled indicator-count bucket, since none of those zeroed inputs can
cross `compute_confidence`'s own >0 thresholds) rather than reimplementing
its bucket table a second time (code-review finding, Phase 4) -- this
function -- deliberately -- isn't handed the graph/fraud-classifier context
that would make those four inputs non-zero. This is a real, documented
simplification, not a silent behavior difference: alerts.py's caller
(`scripts/run_detection_pipeline.py`) already has that fuller data available
and could pass real values through a future revision if exact archive parity
is ever needed.

Known gap: `RuleEvaluator.evaluate_rule`'s Tier-1 (single-condition) path
returns the primitive's `DetectionResult`s unmodified except for
`detection_type` -- it never stamps `details["rule_id"]` the way the Tier-2
composite path does. Every seeded built-in rule
(`detection/rules/seed.py`) is Tier-1, so `Alert.rule_ids` is null for all
of them; only custom Tier-2 rules populate it. Not fixed here -- it's
`detection/rules/engine.py`'s (Phase 3, "done") surface, out of this
phase's scope.
"""
from __future__ import annotations

import hashlib
import logging

from sqlalchemy.orm import Session

from db.enums import ActorType, DetectionType, Priority, RiskLevel
from db.models.base import utcnow
from db.models.detection import Alert
from db.repositories.detection import AlertRepository
from detection.scoring.ensemble import EnsembleScorer
from detection.types import DetectionResult

logger = logging.getLogger(__name__)


def make_deterministic_alert_id(
    account_ids: list[str], detection_type: str, date_str: str
) -> str:
    """Same (accounts, pattern, date) always produces the same alert_id, so
    re-detecting an already-known pattern refreshes its existing DB row
    (updating `last_seen_at`) instead of creating a duplicate. `account_ids`
    is sorted first so the same group in a different order still lands on
    the same id. Ported unchanged from
    `archive/fund-flow-tracker/services/common/models.py::
    make_deterministic_alert_id`."""
    content_key = (
        f"{','.join(sorted(str(a) for a in account_ids))}-{detection_type}-{date_str}"
    )
    return f"ALT-{hashlib.sha256(content_key.encode()).hexdigest()[:12].upper()}"


def _to_risk_level(value: str) -> RiskLevel:
    try:
        return RiskLevel(value)
    except ValueError:
        return RiskLevel.MEDIUM


def generate_alerts_from_detection(
    session: Session,
    ensemble_scores: dict[str, float],
    rule_results: dict[str, list[DetectionResult]],
    model_run_id: str | None,
    *,
    actor_type: ActorType,
    actor_id: str | None,
    date_str: str | None = None,
) -> list[Alert]:
    """Create or refresh one `Alert` per `DetectionResult` across every
    detection type in `rule_results`. `DetectionResult`s whose
    `detection_type` string isn't a member of the `DetectionType` enum
    (`db/enums.py` -- e.g. `fan_out`/`fan_in`, which didn't survive the
    Phase 1 schema design, or the generic-aggregate primitive's `custom`)
    are skipped with a warning: `alerts.detection_type` is a hard DB enum
    constraint, so there is no valid row to write for them."""
    repo = AlertRepository(session)
    scorer = EnsembleScorer()
    account_flags = EnsembleScorer.build_flags(rule_results)
    effective_date = date_str or utcnow().strftime("%Y-%m-%d")

    alerts: list[Alert] = []
    for detection_type_str, results in rule_results.items():
        try:
            detection_type = DetectionType(detection_type_str)
        except ValueError:
            logger.warning(
                "skipping %d detection(s) of type %r -- not a valid alerts.detection_type "
                "enum member",
                len(results),
                detection_type_str,
            )
            continue

        for result in results:
            account_ids = sorted({str(a) for a in result.account_ids})
            if not account_ids:
                continue

            primary_account_id = max(account_ids, key=lambda a: ensemble_scores.get(a, 0.0))
            risk_score = float(ensemble_scores.get(primary_account_id, result.score * 100))
            severity = _to_risk_level(result.severity)
            confidence, _indicator_count, _indicators = scorer.compute_confidence(
                primary_account_id,
                account_flags.get(primary_account_id, {}),
                anomaly_score=0.0,
                fraud_prob=0.0,
                pagerank=0.0,
                betweenness=0.0,
            )
            amount = (
                float(result.details.get("total_amount", 0.0))
                if isinstance(result.details, dict)
                else 0.0
            )
            priority = Priority(
                scorer.compute_priority(risk_score, confidence, amount, len(account_ids))
            )
            rule_id = result.details.get("rule_id") if isinstance(result.details, dict) else None
            rule_ids = [rule_id] if rule_id else None

            alert_id = make_deterministic_alert_id(account_ids, detection_type_str, effective_date)
            existing = repo.get(alert_id)
            if existing is None:
                alert = repo.create(
                    alert_id=alert_id,
                    detection_type=detection_type,
                    primary_account_id=primary_account_id,
                    account_ids=account_ids,
                    score=float(result.score),
                    risk_score=risk_score,
                    severity=severity,
                    priority=priority,
                    confidence=confidence,
                    status="open",
                    rule_ids=rule_ids,
                    model_run_id=model_run_id,
                    source="pipeline",
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            else:
                alert = repo.update(
                    alert_id,
                    score=float(result.score),
                    risk_score=risk_score,
                    severity=severity,
                    priority=priority,
                    confidence=confidence,
                    rule_ids=rule_ids,
                    model_run_id=model_run_id,
                    last_seen_at=utcnow(),
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            alerts.append(alert)

    return alerts
