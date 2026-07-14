"""
The PII egress gate — ROADMAP Phase 8, committed decision 9.

**Zero egress, enforced, fail-closed.** This gate stands between a fact bundle
and the network. If it finds PII, it *raises*. It does not strip, mask, or
tokenize.

That choice is the whole point, and it is worth being precise about why:

    "It never left our perimeter"      is a claim a bank can verify.
    "We de-identified it on the way out" is a claim a bank must trust.

A silent strip produces the second claim, and it produces it *from the same code
path as a bug*: if the stripper misses a field, nothing anywhere records that it
happened. A raise produces the first claim, loudly, and a missed field becomes a
failed request instead of a quiet disclosure. Fail-closed costs us an occasional
outage; fail-open costs us a customer's PAN.

This is the **braces**. The **belt** is that `orchestration/tools/catalog.py` is
*shaped* so PII is never in a tool's return value to begin with — and that belt
already caught a real leak (`build_case_relationship_graph` returning
`customer.name`). Two independent mechanisms, because decision 9's claim is
absolute and a single mechanism with a single bug would make it false.

## Two detectors, because they fail differently

1. **Known-value scan** (exact, no false positives). Loads the actual PII of the
   entities *in this case* — the customers behind its accounts, its transactions'
   narration/purpose, its notes — straight from the columns `db/pii.py` registers,
   and checks whether any of those literal strings appears in the bundle. This is
   the precise claim: *we compared what we are about to send against this case's
   real PII, byte for byte.*

2. **Format scan** (catches PII the first detector cannot see). A value could
   arrive from *outside* the case — a bug joining the wrong row, a future tool
   reaching too far. That is a worse leak, and detector 1 would not see it,
   because it only knows this case's values. So we also reject anything *shaped*
   like a real PAN, Aadhaar, or Indian mobile.

**Detector 2 is only safe to run fail-closed because of decision 11.** Demo
identifiers are now deliberately format-*invalid* (`_synthetic_pan` leads with a
digit where a PAN needs a letter; `_synthetic_phone` leads with `1`, not an
allocatable mobile prefix). Had they kept their old real-format shapes, this
detector would have fired on every demo case and the gate would have had to be
weakened or switched off. The demo-data fix and this gate are the same decision
seen from two ends.

## The error never contains the PII

`PIIEgressError` names the *column* and the *fact key*, never the value. An
exception that echoes a PAN into a stack trace, a log aggregator, and an error
tracker has not prevented the disclosure — it has widened it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from db.models.investigation import CaseAccount, Note
from db.models.platform import User, Watchlist
from db.models.reference import Account, Customer, Transaction
from db.pii import PII_COLUMNS

#: Values shorter than this are not scanned as literals. A 1-2 character string
#: ("A", "IN") appears inside unrelated text constantly, and a fail-closed gate
#: that fires on coincidence is one that gets disabled. Names this short are the
#: accepted residual risk; the format scan and the tool shaping both still apply.
_MIN_LITERAL_LENGTH = 3

#: A *real* Indian PAN: five letters, four digits, a letter. No checksum exists,
#: so anything of this shape must be treated as a live tax identifier.
#: Demo PANs lead with a digit (decision 11) and cannot match this.
_REAL_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
#: A *real* Aadhaar: 12 digits, never starting 0 or 1.
#: Demo Aadhaars start with 1 and cannot match this.
_REAL_AADHAAR = re.compile(r"\b[2-9][0-9]{11}\b")
#: A *real* Indian mobile: 10 digits starting 6-9.
#: Demo phones start with 1 and cannot match this.
_REAL_INDIAN_MOBILE = re.compile(r"\b[6-9][0-9]{9}\b")

_FORMAT_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("pan", _REAL_PAN),
    ("aadhaar", _REAL_AADHAAR),
    ("phone", _REAL_INDIAN_MOBILE),
)

#: The customer columns `db/pii.py` registers as PII. Derived from that registry
#: rather than re-listed, so the two cannot drift — `db/pii.py` says explicitly
#: that it *is* the allow-map and must be kept in sync.
_CUSTOMER_PII_COLUMNS: tuple[str, ...] = tuple(
    c.column for c in PII_COLUMNS if c.table == "customers"
)
_TRANSACTION_PII_COLUMNS: tuple[str, ...] = tuple(
    c.column for c in PII_COLUMNS if c.table == "transactions"
)


class PIIEgressError(Exception):
    """PII was found in something about to be sent to a third-party model.

    Deliberately carries the column and the fact key but **never the value** —
    see the module docstring. Fail closed: the caller must abandon the
    interaction, not retry it with the offending field removed, because a bundle
    that contained PII once is a bundle whose shaping is wrong."""


@dataclass(frozen=True)
class CasePII:
    """This case's real PII, loaded once.

    Separated from the assertion so the (bounded but non-trivial) load happens
    **once per interaction** rather than once per tool call. Code-review finding:
    the gate previously re-ran an N+1 account/customer walk plus a 500-row-per-
    account transaction hydration on every invocation — and, now that the gate
    runs on every tool dispatch, that would have been paid a dozen times per
    explanation to read two columns the project's own metrics record as
    0-populated across all 8,002 transactions."""

    case_id: str
    values: tuple[tuple[str, str], ...]  # (column, value)


def load_case_pii(session: Session, case_id: str) -> CasePII:
    """Every real PII value reachable from this case, in four bulk queries.

    Bulk, not N+1: a previous version walked `AccountRepository.get` and
    `CustomerRepository.get` one row at a time and hydrated up to 500 full
    `Transaction` ORM objects per account — the exact N+1 shape Phase 7 already
    fixed once elsewhere. These select only the PII columns, and — importantly —
    with **no row cap**: the old `list_for_account_in_window` call silently
    stopped at 500 transactions per account, so narration on transaction #501 was
    never checked. A fail-*closed* gate with a silent 500-row blind spot is a
    fail-*open* gate that looks reassuring."""
    values: list[tuple[str, str]] = []

    account_ids = list(
        session.scalars(select(CaseAccount.account_id).where(CaseAccount.case_id == case_id))
    )
    if account_ids:
        customer_ids = [
            cid
            for cid in session.scalars(
                select(Account.customer_id).where(Account.account_id.in_(account_ids))
            )
            if cid
        ]
        if customer_ids:
            cols = [getattr(Customer, c) for c in _CUSTOMER_PII_COLUMNS]
            for row in session.execute(
                select(*cols).where(Customer.customer_id.in_(customer_ids))
            ):
                for column, value in zip(_CUSTOMER_PII_COLUMNS, row, strict=True):
                    if isinstance(value, str) and value.strip():
                        values.append((f"customers.{column}", value.strip()))

        txn_cols = [getattr(Transaction, c) for c in _TRANSACTION_PII_COLUMNS]
        for row in session.execute(
            select(*txn_cols).where(
                or_(
                    Transaction.source_account.in_(account_ids),
                    Transaction.dest_account.in_(account_ids),
                )
            )
        ):
            for column, value in zip(_TRANSACTION_PII_COLUMNS, row, strict=True):
                if isinstance(value, str) and value.strip():
                    values.append((f"transactions.{column}", value.strip()))

    for body in session.scalars(select(Note.body).where(Note.case_id == case_id)):
        if isinstance(body, str) and body.strip():
            values.append(("notes.body", body.strip()))

    # `users` and `watchlist` are NOT case-scoped, so they are scanned whole.
    # Both are small, curated tables (investigators; a compliance watchlist), not
    # the 166k-row customers table. Code-review finding: these are registered in
    # `db/pii.py` and were silently unscanned, while this module claimed to check
    # "the columns db/pii.py registers" — an inaccurate broad claim is worse than
    # an accurate narrow one in exactly the audit this gate exists for.
    for email, full_name in session.execute(select(User.email, User.full_name)):
        for column, value in (("users.email", email), ("users.full_name", full_name)):
            if isinstance(value, str) and value.strip():
                values.append((column, value.strip()))

    for entity_value in session.scalars(select(Watchlist.entity_value)):
        if isinstance(entity_value, str) and entity_value.strip():
            values.append(("watchlist.entity_value", entity_value.strip()))

    return CasePII(case_id=case_id, values=tuple(values))


def assert_no_pii_egress(facts: dict[str, Any], case_pii: CasePII) -> None:
    """Raise `PIIEgressError` if `facts` contains any PII. Returns `None` on
    success; the absence of an exception IS the guarantee.

    Call this on anything about to be handed to a model — a tool result, a fact
    bundle — not merely on what gets persisted afterwards. The thing being
    asserted about is the bytes that actually leave."""
    string_leaves = _string_leaves(facts)

    _assert_no_known_pii_values(string_leaves, case_pii)
    _assert_nothing_shaped_like_pii(string_leaves)


def _string_leaves(facts: dict[str, Any]) -> list[tuple[str, str]]:
    """Every string value in the bundle, as `(fact_key, value)`.

    **Strings only, and that is load-bearing.** JSON serialises numbers unquoted,
    so scanning a serialised blob would run the format detectors across amounts
    too — and a transaction total of `9876543210.0` (Rs 9.87bn) matches the
    Indian-mobile pattern exactly. On a *fail-closed* gate that is not a cosmetic
    false positive: it would refuse to explain a legitimate high-value case, which
    is precisely the kind of case anyone actually cares about. A PAN, Aadhaar or
    phone is always a string column, so restricting the scan to string leaves
    costs no coverage and removes the entire false-positive class."""
    out: list[tuple[str, str]] = []

    def walk(value: Any, key: str) -> None:
        if isinstance(value, str):
            out.append((key, value))
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{key}.{k}")
        elif isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                walk(v, f"{key}[{i}]")

    for key, value in facts.items():
        walk(value, key)
    return out


def _assert_no_known_pii_values(
    string_leaves: list[tuple[str, str]], case_pii: CasePII
) -> None:
    """Detector 1 — exact, this case's real PII."""
    known = [(c, v) for c, v in case_pii.values if len(v) >= _MIN_LITERAL_LENGTH]
    for fact_key, leaf in string_leaves:
        for column, value in known:
            # Substring, not equality: a PII value can be embedded in a longer
            # string (a narration mentioning a name, a note quoting a phone).
            if value in leaf:
                raise PIIEgressError(
                    f"payload for case {case_pii.case_id!r} contains the value of PII "
                    f"column {column!r} (in key {fact_key!r}). Tools must be SHAPED so "
                    f"PII is never in a return value (decision 9) — the fix belongs in "
                    f"the tool, not here. Value withheld from this message on purpose."
                )


def _assert_nothing_shaped_like_pii(string_leaves: list[tuple[str, str]]) -> None:
    """Detector 2 — anything *shaped* like real PII, wherever it came from."""
    for fact_key, leaf in string_leaves:
        for label, pattern in _FORMAT_DETECTORS:
            if pattern.search(leaf) is not None:
                raise PIIEgressError(
                    f"fact bundle contains a value matching the format of a real {label} "
                    f"(in fact key {fact_key!r}). It is not among this case's known PII, "
                    f"which makes it a worse leak, not a lesser one — something reached "
                    f"outside the case. Value withheld from this message on purpose."
                )
