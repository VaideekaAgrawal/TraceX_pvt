"""PII re-hydration — ROADMAP Phase 10, committed decision 9.

The model reasons over `customer_id`, a durable non-identifying pseudonym it is
handed by the tools; it is never given a name. This maps `customer_id -> name`
**only in the reply shown to the investigator**, and only for the ids that
actually appeared in the fact bundle the model saw. The map is built per request,
used once, and discarded — it is never persisted, so `ai_interactions` keeps
`customer_id` and stays PII-free at rest.

That ordering is the whole point of decision 9: *the name never crossed to the
model* (provable — the PII egress gate would have raised), and yet the
investigator still gets a name back, because re-hydration happens on this side of
the boundary, after grounding and validation are done against the tokenised
(customer_id) text.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from db.repositories.reference import CustomerRepository


def collect_customer_ids(facts: dict[str, Any]) -> set[str]:
    """The `customer_id` values present in a flattened fact bundle — the exact
    set that could appear in the model's answer, and therefore the only ids worth
    resolving to names."""
    ids: set[str] = set()
    for key, value in facts.items():
        if not isinstance(value, str) or not value:
            continue
        if key == "customer_id" or key.endswith(".customer_id"):
            ids.add(value)
    return ids


def build_name_map(session: Session, customer_ids: set[str]) -> dict[str, str]:
    """`{customer_id: name}` for the given ids, skipping any without a name. One
    bulk query (`list_by_ids`), not N+1."""
    if not customer_ids:
        return {}
    rows = CustomerRepository(session).list_by_ids(list(customer_ids))
    return {r.customer_id: r.name for r in rows if r.name}


def rehydrate(text: str, name_map: dict[str, str]) -> str:
    """Replace each `customer_id` in `text` with `"Name (customer_id)"`.

    The id is kept alongside the name rather than replaced outright, so the
    investigator sees who it is *and* can still cross-reference the pseudonym that
    appears in the audited `ai_interactions` record — re-hydration for readability
    without severing the audit trail. Longest ids first, so an id that is a prefix
    of another is not partially rewritten."""
    if not name_map:
        return text
    for cid in sorted(name_map, key=len, reverse=True):
        text = text.replace(cid, f"{name_map[cid]} ({cid})")
    return text
