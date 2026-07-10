"""
AI Prioritization Queue -- orchestration only, no new ML (ROADMAP Phase 4
plan). The bandit itself is already built (Phase 3,
`detection.rl.bandit.LinUCBAgent`); this module only re-ranks alerts through
it.

Caps the number of alerts actually re-ranked at `_RL_CANDIDATE_CAP`,
replicating the archive's `InvestigationService._RL_CANDIDATE_CAP = 200`
("only the top N by risk score get re-ranked, keeping the queue fast") --
alerts beyond the cap are still returned, just appended after the ranked
block in their original risk_score order, not dropped.

`Alert` rows don't carry every raw signal `LinUCBAgent.build_context` wants
(no `anomaly_score`/`fraud_probability`/role/amount/income columns on
`alerts` -- see `docs/DATA_SCHEMA.md` §3.2's column list). To still feed it
real signal beyond a single alert's composite `risk_score` (per the ROADMAP
Phase 4 plan's instruction that `generate_alerts_from_detection` "must
preserve enough raw signal, not just the final composite risk_score, or
LinUCBAgent.build_context can't be fed"), this module groups the candidate
alerts by `primary_account_id` and builds each account's `patterns`/
`pattern_count`/`has_*` dims from every alert type that account has fired
across the candidate set (via the union of their `detection_type`s) --
genuine multi-alert signal, not a single-row default. The remaining dims
that truly have no source on `alerts` (anomaly_score, fraud_probability,
role, amount, income_ratio, channel_diversity) default to their zero/
"unknown" value; this is a real, documented data-availability gap given the
frozen Alert schema, not an oversight.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.models.detection import Alert
from detection.rl.bandit import LinUCBAgent

#: Mirrors the archive's `InvestigationService._RL_CANDIDATE_CAP` exactly --
#: only the top N alerts by `risk_score` get re-ranked, keeping the queue
#: fast on a large unassigned backlog.
_RL_CANDIDATE_CAP = 200


def _build_account_features(alerts_for_account: list[Alert]) -> dict[str, Any]:
    """Adapt every `Alert` row for one `primary_account_id` into the flat
    feature dict `LinUCBAgent.build_context` expects."""
    patterns = sorted({str(a.detection_type) for a in alerts_for_account})
    related_accounts: set[str] = set()
    for alert in alerts_for_account:
        related_accounts.update(alert.account_ids)
    best_risk_score = max((a.risk_score for a in alerts_for_account), default=0.0)
    return {
        "risk_score": best_risk_score,
        "role": "NORMAL",  # not persisted on `alerts` -- see module docstring
        "patterns": patterns,
        "anomaly_score": 0.0,  # not persisted on `alerts` -- see module docstring
        "fraud_probability": 0.0,  # not persisted on `alerts` -- see module docstring
        "total_in_flow": 0.0,
        "total_out_flow": 0.0,
        "total_amount": 0.0,  # not persisted on `alerts` -- see module docstring
        "counterparties": max(len(related_accounts) - 1, 0),
        "declared_annual_income": 0.0,  # not persisted on `alerts` -- see module docstring
        "channel_diversity": 1,  # not persisted on `alerts` -- see module docstring
    }


def rank_alert_queue(session: Session, alerts: list[Alert]) -> list[Alert]:
    """Re-rank `alerts` by LinUCB UCB score, grouped by
    `primary_account_id` (alerts sharing an account are ranked/returned as a
    block). Only the top `_RL_CANDIDATE_CAP` alerts by `risk_score` are
    actually re-ranked; the rest are appended afterward, unranked, in their
    original `risk_score`-descending order. Read-only -- `LinUCBAgent.
    rank_accounts`/`.score` never mutate `A`/`b`, so this never flushes or
    needs a commit."""
    if not alerts:
        return []

    by_risk = sorted(alerts, key=lambda a: a.risk_score, reverse=True)
    candidates, overflow = by_risk[:_RL_CANDIDATE_CAP], by_risk[_RL_CANDIDATE_CAP:]

    by_account: dict[str, list[Alert]] = {}
    for alert in candidates:
        by_account.setdefault(alert.primary_account_id, []).append(alert)
    for group in by_account.values():
        group.sort(key=lambda a: a.risk_score, reverse=True)

    account_dicts = [
        {"account_id": account_id, **_build_account_features(group)}
        for account_id, group in by_account.items()
    ]

    agent = LinUCBAgent(session)
    ranked_accounts = agent.rank_accounts(account_dicts)

    ranked_alerts: list[Alert] = []
    for ranked in ranked_accounts:
        ranked_alerts.extend(by_account[ranked["account_id"]])

    return ranked_alerts + overflow
