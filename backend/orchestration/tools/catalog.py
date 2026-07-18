"""
The fixed tool catalog — ROADMAP Phase 8, slice 2.

Twelve tools, each a thin wrapper over an **already-built** Phase 5-7 function.
No tool computes anything new: if a number can reach the model, some
already-tested investigation-layer function produced it. That is what makes a
recommendation reconstructable by a regulator without trusting the model.

Three properties are enforced **in code here**, not requested in a prompt. A
prompt instruction is a suggestion to a model; these are not.

1. **`case_id` is bound at construction and is never a tool argument.** No
   schema in this module has a `case_id` property, so the model has no way to
   express "look at a different case" — it is not a rule it might break, it is a
   sentence it cannot say. `ToolCatalog` closes over one case for its lifetime.

2. **Every account-id argument is validated against that case's scope**, via the
   same `_load_scoped_account` the HTTP routes use. An out-of-case account
   returns a tool **error**, never data. Reusing the routes' own function rather
   than re-implementing the check is deliberate: a case-scoping rule that exists
   in two places will eventually disagree in two places, and the copy the AI path
   uses is the one where a divergence leaks another investigator's case.

3. **Tools return structured fact dicts, never prose.** The model gets numbers
   and identifiers it must cite (slice 3's grounding contract), not sentences it
   can paraphrase into something subtly untrue.

**PII (committed decision 9).** Tools are *shaped* so PII is never in the return
value: `customer_id`, `risk_rating`, `kyc_status`, `income_bracket` — never
`name`, `pan`, `aadhaar`, `phone`. This is the "belt"; the fail-closed egress
gate (`orchestration/redaction.py`, slice 4) is the "braces". Both exist because
"it never left our perimeter" is a claim a bank can verify, and "we de-identified
it on the way out" is a materially weaker one. `tests/orchestration/tools/
test_catalog_pii.py` asserts this catalog-wide against real PII values rather
than trusting this docstring.

**Strict schemas.** Every tool emits `strict: true` with
`additionalProperties: false`. Under OpenAI's strict-mode rules *every* property
must appear in `required`, so genuinely optional arguments are typed as nullable
(`["integer", "null"]`) and `None` means "use the server-side default" — the
model cannot omit a key, only pass null. `dispatch` re-validates argument names
anyway: strict mode is the provider's promise, and a security boundary should
not rest on a promise made by the thing it is constraining.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from db.enums import ActorType
from db.repositories.detection import AlertRepository
from db.repositories.investigation import CaseAccountRepository, CaseRepository
from db.repositories.reference import AccountRepository, CustomerRepository, TransactionRepository
from foundation.auth import _load_scoped_account
from investigation import (
    behavior_analysis,
    case_graph,
    path_facts,
    previous_alerts,
    relationship_graph,
    similar_cases,
    timeline,
    transaction_search,
)
from investigation.account_facts import transaction_stats
from investigation.case_graph import CASE_SCOPE_TRANSACTION_LIMIT
from investigation.graph_filters import MAX_RADIUS, GraphFilters, get_filtered_ego_graph
from orchestration.redaction import CasePII, assert_no_pii_egress, load_case_pii

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """A tool could not run as asked (unknown tool, bad arguments, or an
    out-of-scope account). Surfaced to the model as a structured error result so
    it can correct course — never as data, and never silently as an empty
    success, which the model would happily narrate as "no activity found"."""


@dataclass(frozen=True)
class Tool:
    """One tool. `handler` receives already-validated keyword arguments and the
    bound session/case from the catalog, and returns a fact dict."""

    name: str
    description: str
    properties: dict[str, Any]
    handler: Callable[..., dict[str, Any]]

    def schema(self) -> dict[str, Any]:
        """OpenAI-compatible function schema. All properties are `required`
        (strict-mode rule); optionality is expressed as a nullable type."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "strict": True,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
                    "required": sorted(self.properties),
                    "additionalProperties": False,
                },
            },
        }


# ── Reusable property fragments ───────────────────────────────────────────
# NB: no `case_id` fragment exists, and that is the point — see module docstring.

_ACCOUNT_ID = {
    "type": "string",
    "description": "An account id that is already linked to this case.",
}


def _nullable(type_: str, description: str) -> dict[str, Any]:
    return {"type": [type_, "null"], "description": f"{description} Pass null for the default."}


class ToolCatalog:
    """The twelve tools, bound to exactly one case for their lifetime."""

    def __init__(
        self,
        session: Session,
        case_id: str,
        *,
        actor_type: ActorType,
        actor_id: str | None,
    ) -> None:
        self._session = session
        self._case_id = case_id
        self._actor_type = actor_type
        self._actor_id = actor_id
        self._case_pii: CasePII | None = None
        self._tools: dict[str, Tool] = {t.name: t for t in self._build()}

    # ── public surface ────────────────────────────────────────────────────

    @property
    def case_id(self) -> str:
        return self._case_id

    def schemas(self) -> list[dict[str, Any]]:
        """The `tools=` payload for a chat-completions call."""
        return [self._tools[name].schema() for name in TOOL_NAMES]

    @property
    def case_pii(self) -> CasePII:
        """This case's real PII, loaded once and reused for every dispatch.

        Lazy so constructing a catalog stays cheap, cached so the gate does not
        re-query per tool call."""
        if self._case_pii is None:
            self._case_pii = load_case_pii(self._session, self._case_id)
        return self._case_pii

    def dispatch(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run one tool, and **gate its result before returning it**.

        Raises `ToolError` for anything the model got wrong, and `PIIEgressError`
        if the tool's own output carries PII.

        **The gate lives here because this is where egress actually begins.**
        Code-review finding: it previously ran only inside
        `gateway.generate_and_persist_explanation`, i.e. at *persist* time — but
        in a tool-calling loop the tool results are sent to the model as `role:
        "tool"` messages long before anything is persisted, so every tool payload
        reached the third-party model without ever passing the gate. The check was
        in the wrong place, and a Phase 9 agent would have sailed straight past it.

        Putting it on `dispatch` means no caller can bypass it: any loop, present
        or future, that gets a fact from a tool has already been through the gate,
        by construction rather than by remembering to."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool {name!r}; available: {', '.join(TOOL_NAMES)}")

        args = dict(arguments or {})

        # Defense in depth against a model (or a provider that silently drops
        # strict mode) inventing an argument. `case_id` is called out by name
        # because it is the one the model would most usefully forge.
        unknown = set(args) - set(tool.properties)
        if unknown:
            raise ToolError(
                f"tool {name!r} got unexpected argument(s) {', '.join(sorted(unknown))}; "
                f"accepts: {', '.join(sorted(tool.properties)) or '(none)'}"
            )

        # Nullable-for-default: strip nulls so handlers see real defaults.
        args = {k: v for k, v in args.items() if v is not None}

        # Any account the model names must be in THIS case's scope.
        if "account_id" in args:
            args["account_id"] = self._require_scoped_account(str(args["account_id"]))

        result = tool.handler(**args)

        # Belt (the tool is shaped so PII isn't in the payload) AND braces (this
        # asserts it, fail-closed). Raises PIIEgressError rather than stripping —
        # "it never left our perimeter" is verifiable; "we de-identified it" is not.
        assert_no_pii_egress(result, self.case_pii)
        return result

    # ── internals ─────────────────────────────────────────────────────────

    def _require_scoped_account(self, account_id: str) -> str:
        """Validate `account_id` against this case's linked accounts, reusing the
        HTTP routes' own scoping core so the two paths cannot drift.

        `_load_scoped_account` signals failure with `HTTPException` because its
        first caller was a route. Converting that to `ToolError` here — rather
        than duplicating the check with non-HTTP error handling — keeps the
        scoping rule in exactly one place. The HTTPException never escapes this
        method, so nothing outside it has to know it exists.

        Note the 404 body is reused verbatim and deliberately does not
        distinguish "no such account" from "exists, but not in your case": that
        non-disclosure is the whole reason the routes 404 instead of 403, and it
        matters at least as much here, where the caller is a language model."""
        case = CaseRepository(self._session).get(self._case_id)
        if case is None:
            raise ToolError(f"case {self._case_id!r} does not exist")
        try:
            account, _ = _load_scoped_account(account_id, case, self._session)
        except HTTPException as exc:
            raise ToolError(f"account {account_id!r}: {exc.detail}") from exc
        return account.account_id

    def _scoped_account_ids(self) -> list[str]:
        return CaseAccountRepository(self._session).list_account_ids_for_case(self._case_id)

    # ── the catalog ───────────────────────────────────────────────────────

    def _build(self) -> list[Tool]:
        return [
            Tool(
                name="get_case_summary",
                description=(
                    "Overview of the case under investigation: status, level, priority, "
                    "risk and network-risk scores, linked accounts, and every alert that "
                    "fired, with its detection type and score."
                ),
                properties={},
                handler=self._case_summary,
            ),
            Tool(
                name="get_account_facts",
                description=(
                    "Aggregate transaction statistics and non-identifying customer "
                    "attributes for one account in this case: totals in/out, transaction "
                    "and counterparty counts, channel breakdown, risk score, occupation, "
                    "declared income, and inflow_pct_of_declared_income (inflows as a "
                    "percentage of declared annual income — use this value directly, do "
                    "not compute the ratio yourself)."
                ),
                properties={"account_id": _ACCOUNT_ID},
                handler=self._account_facts,
            ),
            Tool(
                name="get_money_flow",
                description=(
                    "Direct (1-hop) fund flow into and out of one account: each "
                    "counterparty with its total amount, transaction count, and "
                    "pct_of_total — the share of the account's inflow or outflow it "
                    "represents. Use pct_of_total rather than computing percentages."
                ),
                properties={"account_id": _ACCOUNT_ID},
                handler=self._money_flow,
            ),
            Tool(
                name="get_ego_graph",
                description=(
                    "The N-hop transaction neighbourhood around one account, within this "
                    "case only, with optional filters. Nodes carry risk score and role; "
                    f"edges carry amount, channel and timestamp. Radius is clamped to "
                    f"{MAX_RADIUS}."
                ),
                properties={
                    "account_id": _ACCOUNT_ID,
                    "radius": _nullable("integer", f"Hops to expand, 1-{MAX_RADIUS}."),
                    "suspicious_only": _nullable(
                        "boolean", "Keep only accounts flagged suspicious."
                    ),
                    "min_amount": _nullable("number", "Drop transactions below this amount."),
                    "direction": {
                        "type": ["string", "null"],
                        "enum": ["in", "out", None],
                        "description": "Restrict to inbound or outbound edges. "
                        "Pass null for both.",
                    },
                },
                handler=self._ego_graph,
            ),
            Tool(
                name="get_ego_graph_summary",
                description=(
                    "A COMPACT summary of the N-hop transaction neighbourhood around one "
                    "account: node and edge counts, total flow, the highest-risk accounts, "
                    "and the largest individual flows — without the full node/edge dump. "
                    "Prefer this over get_ego_graph for reasoning about network shape; only "
                    "reach for the full get_ego_graph when a specific edge or node is needed."
                ),
                properties={
                    "account_id": _ACCOUNT_ID,
                    "radius": _nullable("integer", f"Hops to expand, 1-{MAX_RADIUS}."),
                },
                handler=self._ego_graph_summary,
            ),
            Tool(
                name="get_network_risk",
                description=(
                    "The case's network risk score and the structural reasons behind it "
                    "(e.g. high-centrality accounts, links to prior-SAR entities)."
                ),
                properties={},
                handler=self._network_risk,
            ),
            Tool(
                name="find_similar_cases",
                description=(
                    "Historically closed cases most similar to this one, by cosine "
                    "similarity over the 16-dimension case feature vector. Each result "
                    "carries its similarity, typology, and how it was actually resolved."
                ),
                properties={"top_k": _nullable("integer", "How many to return.")},
                handler=self._similar_cases,
            ),
            Tool(
                name="get_relationships",
                description=(
                    "Non-transactional links between customers in this case — shared "
                    "attributes such as PAN, phone, device or address. Returns the "
                    "attribute TYPE and a confidence, never the shared value itself."
                ),
                properties={},
                handler=self._relationships,
            ),
            Tool(
                name="get_path_recommendation_facts",
                description=(
                    "The structured evidence behind 'what should be investigated next': "
                    "dominant fund-flow paths, shared-attribute adjacency, and adjacency "
                    "to accounts with a prior SAR."
                ),
                properties={},
                handler=self._path_facts,
            ),
            Tool(
                name="get_timeline",
                description=(
                    "Chronological transaction events for one account: timestamp, "
                    "direction, counterparty, amount and channel."
                ),
                properties={"account_id": _ACCOUNT_ID},
                handler=self._timeline,
            ),
            Tool(
                name="get_behavior_analysis",
                description=(
                    "Behavioural change signals for one account: monthly totals, cash "
                    "deposit and transfer trends, dormancy-then-reactivation, and "
                    "velocity increase."
                ),
                properties={"account_id": _ACCOUNT_ID},
                handler=self._behavior,
            ),
            Tool(
                name="search_transactions",
                description=(
                    "Search transactions within this case, filtered by account, amount "
                    "range, channel or direction. Returns matching transactions and a "
                    "total_count."
                ),
                properties={
                    "account_id": {
                        "type": ["string", "null"],
                        "description": "Restrict to one account in this case. "
                        "Pass null to search every account linked to the case.",
                    },
                    "min_amount": _nullable("number", "Minimum transaction amount."),
                    "max_amount": _nullable("number", "Maximum transaction amount."),
                    "direction": {
                        "type": ["string", "null"],
                        "enum": ["in", "out", None],
                        "description": "Inbound or outbound only. Pass null for both.",
                    },
                    "limit": _nullable("integer", "Maximum rows to return."),
                },
                handler=self._search_transactions,
            ),
            Tool(
                name="get_previous_alerts",
                description=(
                    "This account's alert history from OTHER cases — prior alerts, their "
                    "detection types, and whether any resulted in a SAR. Excludes the "
                    "case currently under investigation."
                ),
                properties={"account_id": _ACCOUNT_ID},
                handler=self._previous_alerts,
            ),
        ]

    # ── handlers (each wraps an already-built function) ────────────────────

    def _case_summary(self) -> dict[str, Any]:
        case = CaseRepository(self._session).get(self._case_id)
        if case is None:
            raise ToolError(f"case {self._case_id!r} does not exist")
        alerts = AlertRepository(self._session).list_for_case(self._case_id)
        return {
            "case_id": case.case_id,
            "status": str(case.status),
            "level": str(case.level),
            "priority": str(case.priority),
            "risk_score": case.risk_score,
            "network_risk_score": case.network_risk_score,
            "primary_account_id": case.primary_account_id,
            "account_ids": self._scoped_account_ids(),
            "alerts": [
                {
                    "alert_id": a.alert_id,
                    "detection_type": str(a.detection_type),
                    "primary_account_id": a.primary_account_id,
                    "account_ids": a.account_ids,
                    "score": a.score,
                    "risk_score": a.risk_score,
                    "severity": str(a.severity),
                    "confidence": a.confidence,
                    "rule_ids": a.rule_ids or [],
                }
                for a in alerts
            ],
        }

    def _account_facts(self, *, account_id: str) -> dict[str, Any]:
        account = AccountRepository(self._session).get(account_id)
        txns = TransactionRepository(self._session).list_for_account_in_window(
            account_id, limit=CASE_SCOPE_TRANSACTION_LIMIT
        )
        stats = transaction_stats(txns, account_id)

        customer: dict[str, Any] = {}
        if account is not None and account.customer_id is not None:
            row = CustomerRepository(self._session).get(account.customer_id)
            if row is not None:
                # Deliberately projected, not spread: name/pan/aadhaar/phone/
                # email/address/employer are all PII and must never reach a
                # prompt (decision 9). `customer_id` is an internal identifier,
                # not an identity.
                customer = {
                    "customer_id": row.customer_id,
                    "entity_type": str(row.entity_type),
                    "risk_rating": str(row.risk_rating) if row.risk_rating else None,
                    "occupation": row.occupation,
                    "declared_annual_income": (
                        float(row.declared_annual_income)
                        if row.declared_annual_income is not None
                        else None
                    ),
                    "income_bracket": row.income_bracket,
                }

        # Server-computed so the MODEL never has to derive it. Live measurement
        # (docs/METRICS.md §13) showed the model reliably wants to state inflows
        # as a percentage of declared income — it did so even when the system
        # prompt explicitly forbade computing new numbers — and the grounding
        # validator correctly rejected the claim every time, because the ratio
        # was the model's own arithmetic and no tool had produced it.
        #
        # The fix for "the model keeps deriving X" is never to relax the gate.
        # It is to make a tool compute X, so the figure becomes a citable fact
        # with an auditable provenance. Same precedent as `get_money_flow`
        # returning `pct_of_total` rather than leaving the model to divide.
        income = (customer or {}).get("declared_annual_income")
        total_in = stats.get("total_in")
        inflow_pct_of_declared_income: float | None = None
        if income and total_in is not None:
            inflow_pct_of_declared_income = round(float(total_in) / float(income) * 100.0, 2)

        return {
            "account_id": account_id,
            "branch_city": account.branch_city if account is not None else None,
            "current_risk_score": (
                float(account.current_risk_score)
                if account is not None and account.current_risk_score is not None
                else None
            ),
            **stats,
            "inflow_pct_of_declared_income": inflow_pct_of_declared_income,
            "customer": customer,
        }

    def _money_flow(self, *, account_id: str) -> dict[str, Any]:
        graph = case_graph.build_case_graph_store(self._session, self._scoped_account_ids())
        ego = graph.get_ego_graph(account_id, radius=1)
        # `add_flow_percentages` is what puts `pct_of_total` on each counterparty
        # — so the model is handed the percentage rather than dividing two
        # numbers itself and citing a figure no tool ever produced.
        flow = case_graph.add_flow_percentages(case_graph.shape_money_flow(ego, account_id))
        # Counterparty COUNTS as citable facts. Same precedent as pct_of_total /
        # inflow_pct_of_declared_income: a "3 sources, 2 beneficiaries" summary is
        # the natural thing to say, but the model counting the lists itself is
        # ungrounded arithmetic the validator (correctly) rejects — found live in
        # the Phase 10 Copilot verify. Hand it the counts instead of the list length.
        flow["source_count"] = len(flow.get("sources", []))
        flow["beneficiary_count"] = len(flow.get("beneficiaries", []))
        return flow

    def _ego_graph(
        self,
        *,
        account_id: str,
        radius: int = 1,
        suspicious_only: bool = False,
        min_amount: float | None = None,
        direction: str | None = None,
    ) -> dict[str, Any]:
        filters = GraphFilters(
            suspicious_only=suspicious_only,
            min_amount=min_amount,
            direction=direction,  # type: ignore[arg-type]  # schema enum constrains to in|out
        )
        return get_filtered_ego_graph(
            self._session,
            self._case_id,
            account_id,
            radius=min(radius, MAX_RADIUS),
            filters=filters,
            case_account_ids=self._scoped_account_ids(),
        )

    def _ego_graph_summary(self, *, account_id: str, radius: int = 2) -> dict[str, Any]:
        """A small, citable digest of the ego graph — the Finding-C fix.

        Live measurement (docs/METRICS.md §17) found a full `get_ego_graph`
        return dominated a recommendation's fact bundle: 2,505 of 3,156 facts,
        ~56k tokens, ~$0.17/prompt. An agent reasoning about *network shape*
        (is there a hub? how much flows through? who is riskiest?) does not need
        every edge — it needs the shape. This returns counts and the top few by
        risk/amount, so the model can reason cheaply and still cite real numbers,
        and only fall through to the full `get_ego_graph` when it genuinely needs
        a specific edge. Same underlying, already-gated data — just summarised."""
        graph = get_filtered_ego_graph(
            self._session,
            self._case_id,
            account_id,
            radius=min(radius, MAX_RADIUS),
            filters=GraphFilters(),
            case_account_ids=self._scoped_account_ids(),
        )
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])

        def _risk(node: dict[str, Any]) -> float:
            score = node.get("current_risk_score")
            return float(score) if score is not None else -1.0

        def _amount(edge: dict[str, Any]) -> float:
            amt = edge.get("amount")
            return float(amt) if amt is not None else 0.0

        top_by_risk = sorted(nodes, key=_risk, reverse=True)[:5]
        largest_flows = sorted(edges, key=_amount, reverse=True)[:5]
        node_risks = [_risk(n) for n in nodes if n.get("current_risk_score") is not None]

        return {
            "account_id": account_id,
            "radius": min(radius, MAX_RADIUS),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "total_flow_amount": round(sum(_amount(e) for e in edges), 2),
            "max_node_risk_score": max(node_risks) if node_risks else None,
            "prior_sar_node_count": sum(1 for n in nodes if n.get("has_prior_sar")),
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

    def _network_risk(self) -> dict[str, Any]:
        """Reads the STORED score. Deliberately does not lazily recompute.

        Code-review finding: this used to fall through to
        `network_risk.compute_network_risk` when the score was null, mirroring
        `GET /cases/{id}/network-risk`. But that function ends in
        `CaseRepository.update(...)`, which writes the case row AND an audit_log
        entry stamped with the investigator's actor_id. So a *model* deciding to
        call a "read-only fact tool" would mutate case state and forge an audit
        entry that reads as though the human did it — and if the surrounding
        request never commits, the score is silently discarded and recomputed on
        every call, so the lazy cache never even fills.

        A fact tool reads facts. Scoring is a state change and belongs to an
        explicit, human-attributed action (the existing recompute route). A null
        score is itself an honest fact, and the model can say so."""
        case = CaseRepository(self._session).get(self._case_id)
        if case is None:
            raise ToolError(f"case {self._case_id!r} does not exist")
        return {
            "case_id": case.case_id,
            "network_risk_score": case.network_risk_score,
            "network_risk_reasons": case.network_risk_reasons,
            "computed": case.network_risk_score is not None,
        }

    def _similar_cases(self, *, top_k: int = 5) -> dict[str, Any]:
        results = similar_cases.find_similar_cases(
            self._session,
            self._case_id,
            top_k=top_k,
            actor_type=self._actor_type,
            actor_id=self._actor_id,
        )
        return {
            "case_id": self._case_id,
            "similar_cases": [
                {
                    "case_id": r.case_id,
                    "similarity": r.similarity,
                    "typology": r.typology,
                    "outcome": str(r.outcome) if r.outcome is not None else None,
                }
                for r in results
            ],
        }

    def _relationships(self) -> dict[str, Any]:
        graph = relationship_graph.build_case_relationship_graph(
            self._session, self._case_id, self._scoped_account_ids()
        )
        # The EDGES are safe for free: `Relationship.value_hash` means an edge
        # carries `shared_attribute: "pan"` and a confidence, never the PAN.
        #
        # The NODES are not. `build_case_relationship_graph` puts `customer.name`
        # on every node — correct for the Relationship Explorer, where a human
        # investigator is entitled to see who they are looking at, and wrong
        # here, where the payload is bound for a third-party model. Caught by
        # `tests/orchestration/tools/test_catalog_pii.py`, which is the entire
        # reason that test asserts against real PII values rather than trusting
        # this module's own docstring. Project rather than mutate: the UI's need
        # for names is legitimate, so the shaping belongs on the AI path only.
        return {
            **graph,
            "nodes": [
                {"customer_id": n["customer_id"], "in_case_scope": n["in_case_scope"]}
                for n in graph.get("nodes", [])
            ],
        }

    def _path_facts(self) -> dict[str, Any]:
        facts = path_facts.compute_path_recommendation_facts(self._session, self._case_id)
        return {
            "case_id": facts.case_id,
            "primary_account_id": facts.primary_account_id,
            "fund_flow": [vars(f) for f in facts.fund_flow],
            "shared_attribute_adjacency": [vars(f) for f in facts.shared_attribute_adjacency],
            "prior_sar_adjacency": [vars(f) for f in facts.prior_sar_adjacency],
        }

    def _timeline(self, *, account_id: str) -> dict[str, Any]:
        return timeline.build_timeline(self._session, self._case_id, account_id)

    def _behavior(self, *, account_id: str) -> dict[str, Any]:
        return behavior_analysis.analyze(self._session, self._case_id, account_id)

    def _search_transactions(
        self,
        *,
        account_id: str | None = None,
        min_amount: float | None = None,
        max_amount: float | None = None,
        direction: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return transaction_search.search(
            self._session,
            self._case_id,
            account_id=account_id,
            case_account_ids=self._scoped_account_ids(),
            min_amount=min_amount,
            max_amount=max_amount,
            direction=direction,  # type: ignore[arg-type]  # schema enum constrains to in|out
            limit=limit,
        )

    def _previous_alerts(self, *, account_id: str) -> dict[str, Any]:
        return previous_alerts.summarize(
            self._session, account_id, exclude_case_id=self._case_id
        )


#: The catalog is FIXED. This is the whole action surface the model has, and it
#: doubles as the ordering used in `schemas()` so the tool list is byte-stable
#: across calls (a reordered tool list would silently break prompt caching).
TOOL_NAMES: tuple[str, ...] = (
    "get_case_summary",
    "get_account_facts",
    "get_money_flow",
    "get_ego_graph",
    "get_ego_graph_summary",
    "get_network_risk",
    "find_similar_cases",
    "get_relationships",
    "get_path_recommendation_facts",
    "get_timeline",
    "get_behavior_analysis",
    "search_transactions",
    "get_previous_alerts",
)


def build_tool_catalog(
    session: Session,
    case_id: str,
    *,
    actor_type: ActorType,
    actor_id: str | None,
) -> ToolCatalog:
    """Construct the catalog bound to one case. This is the only supported way
    to get tools: there is no module-level catalog a caller could accidentally
    use unbound, because an unbound catalog would be one whose `case_id` came
    from somewhere other than the server."""
    return ToolCatalog(session, case_id, actor_type=actor_type, actor_id=actor_id)
