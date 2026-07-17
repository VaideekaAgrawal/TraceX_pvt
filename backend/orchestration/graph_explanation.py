"""
AI Investigation Graph explanation -- L2, "what is structurally happening in
this account's network" narrative for the N-hop graph view (`GET .../
accounts/{account_id}/graph`).

**Exactly mirrors `orchestration/account_explanation.py`'s guardrail
pattern** (per that module's own docstring and CLAUDE.md's "AI guardrail
pattern is feature-specific, not global" -- this module re-derives, rather
than assumes, that the existing per-account explanation's safety property
transfers here; it does, because this fact bundle is built the same way:
every fact below is server-computed from already-tested investigation-layer
functions -- ego-graph shape, role classification, cycle detection -- never
attacker-controllable free text. `Transaction.narration`/`purpose` are
deliberately EXCLUDED, same omission `account_explanation.py` makes and
tests, for the same reason.

**Reuse before rebuild** (CLAUDE.md): no new fact-extraction pipeline. Facts
come from `investigation.graph_filters.get_filtered_ego_graph` -- the same
underlying data the Investigation Graph UI itself renders (radius=2,
no filters -- matching `orchestration/tools/catalog.py::_ego_graph_summary`'s
own precedent for a compact, citable digest of an ego-subgraph) -- plus
`detection.scoring.ensemble.RoleClassifier`/`NetworkXGraphStore.
detect_cycles`, both already used the same way by `investigation.
network_risk.compute_network_risk` for a case-wide network risk score. This
module's only new logic is the aggregation (role counts, cycle summary) and
the prompt itself.

Cached in the same `ai_interactions` table, `AiAgent.RECOMMENDATION`, under
`key_field="graph_account_id"` -- a third key disjoint from `account_
explanation`'s `"account_id"` and `pattern_explanation`'s `"alert_id"` in the
same namespace (`orchestration.gateway.find_cached_interaction`'s docstring
already documents those two keys don't collide; a third disjoint key key
follows the same reasoning)."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.enums import ActorType, AiAgent
from db.models.base import utcnow
from db.repositories.investigation import CaseAccountRepository
from db.repositories.orchestration import AiInteractionRepository
from detection.scoring.ensemble import RoleClassifier
from foundation.config import Settings
from investigation.graph_filters import GraphFilters, build_subgraph_store, get_filtered_ego_graph
from orchestration.gateway import (
    ExplanationUnavailableError,
    find_cached_interaction,
    generate_and_persist_explanation,
)
from orchestration.gateway import call_llm as _call_llm

# Re-exported at module level, same convention `account_explanation.py` uses,
# so a caller/test can `orchestration.graph_explanation.ExplanationUnavailableError`
# and this module's own monkeypatch seam (`_call_llm`, resolved in THIS
# module's frame by `generate_and_persist_explanation`'s `call_fn` parameter)
# stays intact.

#: Matches the Investigation Graph UI's own default radius (`api.routes.l2.
#: get_account_graph`'s `radius: int = Query(default=2)`) and `orchestration.
#: tools.catalog.py`'s `_ego_graph_summary` tool's default -- this narrative
#: describes the same neighbourhood the investigator is looking at, not a
#: wider or narrower one.
_DEFAULT_RADIUS = 2

#: Same bounded cycle-detection budget `investigation.network_risk.
#: compute_network_risk` uses for a case-wide graph -- generous relative to
#: `NetworkXGraphStore.detect_cycles`'s own defaults (12/2000) since an ego-
#: subgraph at radius 2 is always small. Not re-imported from that module
#: (its constants are module-private, `_CYCLE_MAX_LENGTH`/`_CYCLE_MAX_
#: CYCLES`) -- duplicated here rather than promoting them out for a second
#: caller, since this bug-fix pass is deliberately scoped small (CLAUDE.md:
#: "prefer correctness and small, reviewable diffs").
_CYCLE_MAX_LENGTH = 8
_CYCLE_MAX_CYCLES = 50

#: How many top-risk accounts / largest flows to cite in the prompt --
#: matches `orchestration.tools.catalog._ego_graph_summary`'s own `[:5]`.
_TOP_N = 5


def _assemble_facts(session: Session, case_id: str, account_id: str) -> dict[str, Any]:
    """Server-computed facts only -- see module docstring for the guardrail
    reasoning behind what is and isn't included here. No `Transaction.
    narration`/`purpose`, no customer PII -- only account ids, roles,
    amounts, and counts, the same shape `_ego_graph_summary`/`account_
    explanation._assemble_facts` already prove safe against the PII egress
    gate (`orchestration.redaction.assert_no_pii_egress`)."""
    case_account_ids = CaseAccountRepository(session).list_account_ids_for_case(case_id)
    ego = get_filtered_ego_graph(
        session,
        case_id,
        account_id,
        radius=_DEFAULT_RADIUS,
        filters=GraphFilters(),
        case_account_ids=case_account_ids,
    )
    nodes = ego.get("nodes", [])
    edges = ego.get("edges", [])

    # A throwaway store scoped to just this ego-subgraph -- same helper
    # `investigation.graph_filters.annotate_nodes` already uses internally to
    # role-classify this exact subgraph, reused here (not rebuilt) so role
    # classification and cycle detection both run over the identical graph.
    store = build_subgraph_store(ego)

    roles = RoleClassifier().classify_all(store)
    role_counts: dict[str, int] = {"SOURCE": 0, "MULE": 0, "SINK": 0, "NORMAL": 0}
    for info in roles.values():
        role = info.get("role", "NORMAL")
        role_counts[role] = role_counts.get(role, 0) + 1

    cycles = store.detect_cycles(max_length=_CYCLE_MAX_LENGTH, max_cycles=_CYCLE_MAX_CYCLES)

    def _risk(node: dict[str, Any]) -> float:
        score = node.get("current_risk_score")
        return float(score) if score is not None else -1.0

    def _amount(edge: dict[str, Any]) -> float:
        amt = edge.get("amount")
        return float(amt) if amt is not None else 0.0

    top_by_risk = sorted(nodes, key=_risk, reverse=True)[:_TOP_N]
    largest_flows = sorted(edges, key=_amount, reverse=True)[:_TOP_N]

    return {
        "account_id": account_id,
        # Cache key field (`orchestration.gateway.find_cached_interaction`'s
        # `key_field="graph_account_id"`) -- deliberately distinct from
        # `account_id` above so this cache namespace never collides with
        # `account_explanation`'s `key_field="account_id"` entries, even
        # though both are `AiAgent.RECOMMENDATION` rows for the same case.
        "graph_account_id": account_id,
        "radius": ego.get("radius"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "role_counts": role_counts,
        "cycle_count": len(cycles),
        "has_cycle": len(cycles) > 0,
        "example_cycle": cycles[0] if cycles else None,
        "prior_sar_node_count": sum(1 for n in nodes if n.get("has_prior_sar")),
        "laundering_flagged_edge_count": sum(1 for e in edges if e.get("is_laundering")),
        "total_flow_amount": round(sum(_amount(e) for e in edges), 2),
        "top_accounts_by_risk": [
            {
                "account_id": n.get("account_id"),
                "role": n.get("role"),
                "current_risk_score": n.get("current_risk_score"),
                "has_prior_sar": bool(n.get("has_prior_sar")),
            }
            for n in top_by_risk
        ],
        "largest_flows": [
            {
                "source_account": e.get("source_account"),
                "dest_account": e.get("dest_account"),
                "amount": _amount(e),
            }
            for e in largest_flows
        ],
    }


def _build_prompt(facts: dict[str, Any]) -> str:
    """Prompt modeled on `account_explanation._build_prompt`'s style
    (compliance-officer voice, cite specific numbers, no bullet points,
    explain jargon in plain English, a handful of sentences, no model-name
    mentions) -- adapted from a single-account explainer to a network-shape
    narrative: which accounts look like sources/mules/sinks and why, whether
    there's a cycle, where money is concentrating."""
    account_id = facts["account_id"]
    role_counts = facts["role_counts"]
    role_text = (
        ", ".join(
            f"{count} {role.lower()}" for role, count in role_counts.items() if count > 0
        )
        or "no classified accounts"
    )

    if facts["has_cycle"]:
        cycle = facts["example_cycle"] or []
        cycle_text = (
            f"Yes -- {facts['cycle_count']} closed transaction cycle(s) detected, e.g. "
            f"{' -> '.join(cycle)} -> {cycle[0] if cycle else ''} (funds returning to an "
            f"account already in the chain, a classic layering/circular-flow signal)"
        )
    else:
        cycle_text = "No closed transaction cycle detected in this view"

    top_risk_text = (
        ", ".join(
            f"{a['account_id']} ({a['role']}, risk {a['current_risk_score'] or 0.0:.0f}/100"
            f"{', prior SAR' if a['has_prior_sar'] else ''})"
            for a in facts["top_accounts_by_risk"]
        )
        or "none scored"
    )
    largest_flow_text = (
        ", ".join(
            f"{f['source_account']} -> {f['dest_account']} (Rs.{f['amount']:,.0f})"
            for f in facts["largest_flows"]
        )
        or "none"
    )

    return f"""You are a senior financial crime analyst writing investigation briefings for \
compliance officers at a bank. Write a clear, professional 4-6 sentence explanation of what is \
structurally happening in the transaction network around account {account_id}.

Network Summary (radius {facts['radius']} hops around {account_id}):
- Accounts in view: {facts['node_count']} ({role_text})
- Transactions in view: {facts['edge_count']}, totaling Rs.{facts['total_flow_amount']:,.0f}
- Transactions already flagged as laundering by prior detection: \
{facts['laundering_flagged_edge_count']}
- Accounts in view with a prior confirmed SAR: {facts['prior_sar_node_count']}
- Transaction cycle detected: {cycle_text}
- Highest-risk accounts in view: {top_risk_text}
- Largest individual money flows in view: {largest_flow_text}

Instructions:
- Explain which accounts function as sources, mules, or sinks and why (based on the role \
counts and highest-risk accounts above), whether a cycle exists and what that structurally \
implies, and where money is concentrating.
- Write as a compliance officer would for an investigation briefing
- Use specific numbers and account IDs from the data above
- Explain any AML jargon you use (e.g. "layering" = moving funds through multiple accounts to \
obscure origin, "smurfing" = splitting a large sum into many smaller transactions, "mule \
account" = an account used to receive and quickly forward funds on someone else's behalf) in \
plain English
- Ground every claim strictly in the facts given above; do not speculate beyond them
- Do NOT use bullet points or headers -- write flowing prose only
- Do NOT mention model names like XGBoost or Isolation Forest
- Maximum 6 sentences"""


def explain_graph(
    session: Session,
    case_id: str,
    account_id: str,
    *,
    settings: Settings,
    actor_type: ActorType,
    actor_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Return `{"account_id", "explanation", "cached", "model",
    "generated_at"}` for the Investigation Graph around `account_id` within
    `case_id`. Validates `account_id` is in the case's scope (defense-in-
    depth -- the real boundary check is the route dependency, `api.routes.
    l2.require_case_scoped_account_read`; this repeats it because this
    function is also directly unit-testable/callable without going through
    HTTP, matching `account_explanation.explain_account`'s precedent).

    Unless `force=True`, checks `ai_interactions` for a prior `RECOMMENDATION`
    interaction for this exact (case, account) keyed on `"graph_account_id"`
    and returns it (`cached=True`) without calling the LLM again. Otherwise
    assembles fresh facts and calls `_call_llm` via `orchestration.gateway.
    generate_and_persist_explanation`: on success, persists a new `ai_
    interactions` row (does NOT commit -- caller owns the transaction
    boundary) and returns `cached=False`; on `ExplanationUnavailableError`,
    returns `cached=False` with the error message surfaced but writes NO
    `ai_interactions` row -- a failure must never be persisted and later
    served back as `cached=True` (same landmine `account_explanation.py`
    documents and regression-tests)."""
    case_account_ids = set(CaseAccountRepository(session).list_account_ids_for_case(case_id))
    if account_id not in case_account_ids:
        raise ValueError(f"account {account_id!r} is not in case {case_id!r}'s scope")

    interaction_repo = AiInteractionRepository(session)
    if not force:
        cached = find_cached_interaction(
            interaction_repo, case_id, AiAgent.RECOMMENDATION,
            key_field="graph_account_id", key_value=account_id,
        )
        if cached is not None:
            return {
                "account_id": account_id,
                "explanation": cached.response_text,
                "cached": True,
                "model": cached.model,
                "generated_at": cached.created_at,
            }

    facts = _assemble_facts(session, case_id, account_id)
    prompt = _build_prompt(facts)

    try:
        interaction = generate_and_persist_explanation(
            session,
            call_fn=_call_llm,
            prompt=prompt,
            settings=settings,
            case_id=case_id,
            facts=facts,
            actor_type=actor_type,
            actor_id=actor_id,
        )
    except ExplanationUnavailableError as exc:
        return {
            "account_id": account_id,
            "explanation": str(exc),
            "cached": False,
            "model": settings.llm_model,
            "generated_at": utcnow(),
        }

    return {
        "account_id": account_id,
        "explanation": interaction.response_text,
        "cached": False,
        "model": interaction.model,
        "generated_at": interaction.created_at,
    }
