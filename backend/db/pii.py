"""
PII column registry — the redaction allow-map `docs/DATA_SCHEMA.md` §0 says
Phase 8's LLM-gateway redaction/tokenization middleware must stay in sync
with: "columns marked 🔒PII must be registered with the LLM-gateway
redaction/tokenization middleware ... they are pseudonymized before any
external-LLM egress and re-hydrated on return. This column list *is* the
redaction allow-map; keep it in sync."

This module does NOT implement redaction (that's Phase 8) — it only records,
in code instead of prose, exactly which `(table, column)` pairs are PII per
the schema doc, so Phase 8 doesn't have to re-derive the list from the doc's
markdown tables by hand.

Scope and judgment calls (recorded here instead of only in a report, per
this task's instructions):

- `PII_COLUMNS` is scoped to columns the doc tags with the literal `🔒PII`
  marker: `customers.{name,pan,aadhaar,phone,email,address,employer}`,
  `transactions.narration`, `users.{email,full_name}`.
- Three columns are included even though their doc row doesn't repeat the
  literal `🔒PII` string, because the doc's own surrounding text ties them
  to the same guardrail/redaction concern:
    - `transactions.purpose` — the doc row reads "declared purpose; same
      guardrail as narration", and narration is 🔒PII + attacker-controllable
      directly above it; the §3.1 reasoning paragraph names both together:
      "narration/purpose are the attacker-controllable fields called out in
      the guardrail spec".
    - `notes.body` — tagged "(🔒 may contain PII)" in the doc; different
      phrasing (conditional "may contain" vs. a flat tag) but unambiguously
      PII-bearing free text an investigator or the copilot can write.
    - `watchlist.entity_value` — tagged "(🔒 if PII)"; conditional on
      `entity_type` (e.g. a CUSTOMER entry may hold a phone/PAN, a DEVICE
      entry holds a device id that isn't personally identifying on its own).
      Included with the conditional noted rather than excluded outright,
      since a redaction middleware has to check the value regardless.
- Two columns carry a `🔒` (lock) annotation in the doc but are deliberately
  EXCLUDED from `PII_COLUMNS`, with the reasoning kept next to the constant
  below rather than only in this docstring:
    - `relationships.value_hash` — doc: "🔒 hashed, not raw". It is a
      one-way hash computed at write time specifically so the raw PII is
      never stored; there is nothing left to pseudonymize or re-hydrate.
    - `ai_interactions.request_text` — doc: "🔒 stored post-sanitization".
      This column holds the *output* of the Phase 8 sanitization/guardrail
      step, not a raw-PII source; it's a consumer of the redaction pipeline,
      not a target for it. Registering it here would make the pipeline
      redact its own already-redacted output.

Phase 8 should treat `PII_COLUMNS` as the starting allow-map and re-review
the two exclusions above once the actual redaction middleware design is
locked, rather than assuming this list is beyond question.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PIIColumn:
    table: str
    column: str
    note: str


PII_COLUMNS: tuple[PIIColumn, ...] = (
    # customers — identity fields, doc §3.1
    PIIColumn("customers", "name", "🔒PII — CSV Entity Name"),
    PIIColumn("customers", "pan", "🔒PII — aspirational (not in current data)"),
    PIIColumn("customers", "aadhaar", "🔒PII — aspirational"),
    PIIColumn("customers", "phone", "🔒PII — aspirational"),
    PIIColumn("customers", "email", "🔒PII — aspirational"),
    PIIColumn("customers", "address", "🔒PII — aspirational"),
    PIIColumn("customers", "employer", "🔒PII — aspirational; relationship explorer"),
    # transactions — attacker-controllable free text, doc §3.1
    PIIColumn(
        "transactions",
        "narration",
        "🔒PII + attacker-controllable → sanitize before any prompt (Phase 8)",
    ),
    PIIColumn(
        "transactions",
        "purpose",
        "declared purpose; doc: 'same guardrail as narration' (judgment call — "
        "row doesn't repeat the 🔒PII tag literally but the §3.1 reasoning "
        "paragraph names narration/purpose together)",
    ),
    # notes — investigator/copilot free text, doc §3.3
    PIIColumn(
        "notes",
        "body",
        "🔒 may contain PII (judgment call — conditional phrasing, still "
        "included as a redaction target)",
    ),
    # users — platform identity fields, doc §3.5
    PIIColumn("users", "email", "🔒PII"),
    PIIColumn("users", "full_name", "🔒PII"),
    # watchlist — conditional on entity_type, doc §3.5
    PIIColumn(
        "watchlist",
        "entity_value",
        "🔒 if PII (judgment call — conditional on entity_type, e.g. CUSTOMER "
        "vs DEVICE/MERCHANT; included so the middleware always checks it)",
    ),
)

# Fast membership checks, e.g. `("customers", "name") in PII_COLUMN_PAIRS`.
PII_COLUMN_PAIRS: frozenset[tuple[str, str]] = frozenset(
    (c.table, c.column) for c in PII_COLUMNS
)


def columns_for_table(table: str) -> tuple[PIIColumn, ...]:
    """PII columns for a single table, e.g. `columns_for_table("customers")`."""
    return tuple(c for c in PII_COLUMNS if c.table == table)
