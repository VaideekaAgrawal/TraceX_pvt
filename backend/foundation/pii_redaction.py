"""
PII redaction/tokenization middleware (ROADMAP Phase 8; `docs/DATA_SCHEMA.md`
§0: "columns marked lock-PII must be registered with the LLM-gateway
redaction/tokenization middleware ... pseudonymized before any external-LLM
egress and re-hydrated on return").

Callers declare, per fact dict, which keys are PII and what kind
(`PIIField`); `redact_facts` swaps every declared value for an opaque
`[KIND_n]` token before the facts (or a prompt built from them) reach an
LLM, and `rehydrate_text` swaps the tokens back for the real values in
whatever text comes back. The `token_map` this produces is a plain dict,
returned to the caller only -- **never written to any repository/column/
session-persisted structure**: it is ephemeral and request-scoped, a fresh
dict on every `redact_facts` call, existing only long enough for the
caller to pass it to `rehydrate_text` once.

Independent of, but cross-checkable against, `db/pii.py`'s existing
column-based PII allow-map: that module tags `(table, column)` pairs the
schema doc marks lock-PII, but it does NOT include `accounts.account_id`/
`customers.customer_id` even though `SYSTEM_DEVELOPMENT_PLAN.md` §9.4
explicitly names "account numbers" among the identities to pseudonymize.
This module therefore treats `"account_id"`/`"customer_id"` as valid `kind`s
in their own right, independent of whether `db/pii.py` happens to tag the
originating column -- a deliberate widening, not an oversight. Most fact
dicts passed here are ad-hoc-shaped (assembled server-side from several
tables/computed values, e.g. `orchestration.account_explanation`'s facts),
not literal `(table, column)` mirrors, so `pii_kind_for_column` below is an
optional convenience for the minority of callers whose fact keys DO mirror
a real column name -- not a requirement every caller must route through.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from db.pii import PII_COLUMN_PAIRS


@dataclass(frozen=True)
class PIIField:
    fact_key: str  # key in the caller's facts dict, e.g. "customer_name"
    #: "name" | "account_id" | "customer_id" | "pan" | "phone" | "email" |
    #: "address" | "generic"
    kind: str


def redact_facts(
    facts: dict[str, Any], pii_fields: Sequence[PIIField]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Returns `(redacted_facts, token_map)`. `token_map` maps
    `token -> original real value`.

    Only keys named in `pii_fields` are touched; every other key in `facts`
    passes through unchanged (including nested values -- this function
    doesn't recurse into dicts/lists, it only redacts declared top-level
    keys, matching how every current fact-assembly function in this
    codebase builds a flat dict).

    The SAME real value declared under two different `PIIField`s collapses
    to ONE token (dedup by value, not by field) -- e.g. if a facts dict
    happens to repeat the same account id under two different keys, both
    get the same token, so `rehydrate_text` doesn't need to guess which
    token a repeated value in the response text refers to.

    Token shape: `f"[{kind.upper()}_{n}]"`, with `n` a per-`kind` counter
    local to this one call (so the first redacted `"account_id"` is
    `[ACCOUNT_ID_1]`, the second distinct one is `[ACCOUNT_ID_2]`, etc.,
    independent of any other kind's counter)."""
    redacted_facts = dict(facts)
    token_map: dict[str, str] = {}
    value_to_token: dict[tuple[str, Any], str] = {}
    counters: dict[str, int] = {}

    for field in pii_fields:
        if field.fact_key not in facts:
            continue
        value = facts[field.fact_key]
        if value is None:
            continue

        dedup_key = (field.kind, value)
        token = value_to_token.get(dedup_key)
        if token is None:
            counters[field.kind] = counters.get(field.kind, 0) + 1
            token = f"[{field.kind.upper()}_{counters[field.kind]}]"
            value_to_token[dedup_key] = token
            token_map[token] = value

        redacted_facts[field.fact_key] = token

    return redacted_facts, token_map


def rehydrate_text(text: str, token_map: dict[str, str]) -> str:
    """Reverse of `redact_facts` -- replaces every token in `text` with its
    real value from `token_map`. A token with no match in `text` is simply
    never substituted (not an error); a `text` with no tokens at all is
    returned unchanged."""
    result = text
    for token, real_value in token_map.items():
        result = result.replace(token, str(real_value))
    return result


def pii_kind_for_column(table: str, column: str) -> str | None:
    """Looks up `db.pii.PII_COLUMN_PAIRS`; returns `"generic"` if `(table,
    column)` is a registered PII column pair, else `None`. Optional
    cross-check for callers whose fact keys happen to mirror a real
    `(table, column)` pair -- NOT required for every caller, and does not
    itself determine the `kind` string to use (the schema doc's PII
    registry doesn't classify columns into `redact_facts`'s `name`/
    `account_id`/`pan`/etc. taxonomy, it only flags "this column is PII"),
    so callers still choose their own `PIIField.kind`; this is a sanity
    check that a fact key IS a registered PII source, not a kind resolver."""
    return "generic" if (table, column) in PII_COLUMN_PAIRS else None
