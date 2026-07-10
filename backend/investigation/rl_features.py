"""
Shared RL feature-dict assembly for `LinUCBAgent.build_context` callers in
this package.

`investigation.prioritization._build_account_features` (built from
`list[Alert]`) and `investigation.cases._case_rl_features` (built from a
`Case`) both need to hand `build_context` the same flat 11-key dict shape,
differing only in the two or three values each source can actually supply
(`risk_score`, `patterns`, `counterparties`) -- the rest are dims neither
`alerts` nor `cases` has a column for (anomaly_score, fraud_probability,
role, amount, income_ratio, channel_diversity), a real, documented
data-availability gap given the frozen Phase 1 schema, not an oversight.
`base_rl_feature_dict` centralizes that defaulting in one place
(code-review finding, Phase 4: the two call sites had duplicated it) while
leaving each source's own extraction logic (grouping alerts by account,
reading `case.typology`, etc.) where it is -- that part genuinely differs
per source and shouldn't be forced into a shared function.
"""
from __future__ import annotations

from typing import Any


def base_rl_feature_dict(
    *, risk_score: float, patterns: list[str], counterparties: int = 0
) -> dict[str, Any]:
    """The common part of the flat feature dict `LinUCBAgent.build_context`
    expects. Dims with no source on `alerts`/`cases` default to their
    zero/"unknown" value: `role`="NORMAL", `anomaly_score`=0.0,
    `fraud_probability`=0.0, `total_in_flow`/`total_out_flow`/
    `total_amount`=0.0, `declared_annual_income`=0.0, `channel_diversity`=1
    (normalizes to a "single known channel" floor, not "no data")."""
    return {
        "risk_score": risk_score,
        "role": "NORMAL",
        "patterns": patterns,
        "anomaly_score": 0.0,
        "fraud_probability": 0.0,
        "total_in_flow": 0.0,
        "total_out_flow": 0.0,
        "total_amount": 0.0,
        "counterparties": counterparties,
        "declared_annual_income": 0.0,
        "channel_diversity": 1,
    }
