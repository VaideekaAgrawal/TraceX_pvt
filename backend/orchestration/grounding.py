"""
The grounding contract — ROADMAP Phase 8, committed decision 8.

**This is the centrepiece of Phase 8, not a sub-task.** Everything else in the
substrate exists to make this enforceable.

The claim we want to be able to make to a bank is: *the model cannot assert a
number it was not handed.* Not "we told it not to make things up" — a prompt
instruction is a request, and a request is not a control. So:

    tools return structured facts  ->  a per-interaction FACT BUNDLE
    the model returns structured claims, each CITING the fact keys it used
    a DETERMINISTIC VALIDATOR rejects any claim it cannot ground

A rejected claim never reaches the investigator. The validator is ordinary
Python: it does not ask the model whether it was honest, and its verdict does
not depend on the model's cooperation.

## Three gates

A claim survives only if all three hold. They are layered deliberately, because
each one alone has a hole the next one closes:

1. **Citation resolves.** Every `fact_key` a claim cites must exist in the
   bundle. Closes: inventing a source outright.
   *Hole:* the model could cite a real key and still misreport its value.

2. **Cited value matches.** For each citation the model also restates the
   `value` it believes that key holds; the validator compares it against what
   the tool actually returned. Closes: citing `total_in` and calling it 9.4
   million when the tool said 10,000.
   *Hole:* the structured citations could all be correct while the prose beside
   them says something else entirely — and the prose is what a human reads.

3. **Every number in the prose is grounded.** Each numeric token in the
   claim's `statement` must appear among the values it cited. Closes the last
   hole: the sentence the investigator actually reads cannot contain a figure
   no tool produced.

Gate 3 is what makes this a control rather than a gesture. It is also the one
that can misfire, so it is deliberately conservative — see `_statement_numbers`.

## What this DOESN'T do

It does not check that a claim is *true*, only that it is *grounded*: that every
number in it came from a tool. A model can still assemble grounded facts into a
misleading narrative, and no validator can fix that — that is what the
investigator, and Phase 9's rule anchors, are for. Grounding is a floor, not a
ceiling, and it is worth being precise about that in the room rather than
overclaiming.

It also deliberately does NOT let the model derive figures. If a claim needs a
ratio or a percentage, a TOOL must compute it (as `get_money_flow` already
returns `pct_of_total`). "The model may not do arithmetic" sounds severe until
you notice that model arithmetic is exactly the thing nobody can audit.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

# Values this close are the same number. Guards against float repr noise
# (0.1 + 0.2) and against a model writing 71.0 as 71 — neither is a fabrication.
_TOLERANCE = 1e-6

#: A numeric token in prose: optional sign, digits with optional thousands
#: separators, optional decimals. Deliberately requires a word boundary and
#: rejects anything glued to a letter or hyphen, so identifiers like `A1`,
#: `DEMO-ACC-004`, `CASE-2026-11` and ISO dates are NOT read as numeric claims.
#: Being conservative here is the right failure direction: a missed number is a
#: gap in gate 3, but a false positive rejects a perfectly good explanation and
#: teaches everyone to switch the validator off.
_NUMBER_IN_PROSE = re.compile(r"(?<![\w.-])[-+]?\d[\d,]*(?:\.\d+)?(?![\w-])")

#: An ISO-ish date, optionally with a time. Removed before number-scanning: a
#: date states *when*, not *how much*.
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?)?Z?")
#: A bare clock time (`12:00:00`). The `12` here is not a quantitative claim —
#: this exact case produced a live false rejection; see `_statement_numbers`.
_CLOCK_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\b")
#: A month-name date (`March 2026`, `in Mar. 2026`). Also a live false rejection:
#: the model opened a claim with "In March 2026, the account received..." and the
#: year was read as an ungrounded quantity. Deliberately requires the month name
#: rather than stripping every 4-digit number, so a genuine amount that happens to
#: look like a year is still subject to gate 3.
_MONTH_YEAR = re.compile(
    r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+\d{4}\b"
)


class GroundingError(Exception):
    """The model's response could not be parsed into claims at all (malformed
    JSON, missing required fields). Distinct from a claim being *rejected*,
    which is a normal, expected outcome and is reported, not raised."""


@dataclass(frozen=True)
class Citation:
    """The model's assertion that `fact_key` holds `value`. Both halves are
    checked: the key must exist, and the value must be what the tool said."""

    fact_key: str
    value: Any


@dataclass(frozen=True)
class Claim:
    statement: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class Rejection:
    claim: Claim
    reason: str

    def __str__(self) -> str:
        return f"{self.reason} — {self.claim.statement!r}"


@dataclass
class GroundingResult:
    """Outcome of validating one model response."""

    accepted: list[Claim] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True only if nothing was rejected. A partially-grounded answer is not
        a safe answer to show an investigator: the ungrounded sentence is
        exactly the one they'd have no way to check."""
        return not self.rejected

    def narrative(self) -> str:
        """The accepted claims as prose, in order. This — and only this — is
        what may be shown to a human."""
        return " ".join(c.statement.strip() for c in self.accepted)


class FactBundle:
    """Everything the tools returned during one interaction, flattened to
    addressable leaf keys.

    A "fact" is a *scalar*, not a tool result. `get_account_facts` returning a
    dict of twelve numbers produces twelve facts, each independently citable
    (`get_account_facts.total_in`). That granularity is the point: a claim cites
    the specific number it used, so the validator can check that number rather
    than waving at the tool call it came from.
    """

    def __init__(self) -> None:
        self._facts: dict[str, Any] = {}
        self._tools_called: list[str] = []

    def add_tool_result(self, tool_name: str, result: dict[str, Any]) -> None:
        """Flatten one tool's output into the bundle under a `tool_name.` prefix.

        Re-calling the same tool overwrites its facts rather than accumulating a
        second copy: the tool is deterministic over the same case, so a second
        call yields the same values, and distinct keys per call would let the
        model cite a stale one."""
        if tool_name not in self._tools_called:
            self._tools_called.append(tool_name)
        for key, value in _flatten(result, prefix=tool_name):
            self._facts[key] = value

    def resolve(self, fact_key: str) -> tuple[bool, Any]:
        """(found, value). Returns a flag rather than raising or using a `None`
        sentinel, because `None` is a legitimate fact value — `network_risk_score`
        is genuinely null on a case nobody has scored yet, and a validator that
        confuses "no such fact" with "the fact is null" would either reject good
        claims or accept invented ones."""
        if fact_key not in self._facts:
            return False, None
        return True, self._facts[fact_key]

    @property
    def facts(self) -> dict[str, Any]:
        """The full bundle — persisted verbatim to `ai_interactions.facts`, so an
        auditor can re-run the validator against exactly what the model saw."""
        return dict(self._facts)

    @property
    def tools_called(self) -> list[str]:
        """Persisted to `ai_interactions.tools_called`."""
        return list(self._tools_called)

    def __len__(self) -> int:
        return len(self._facts)


def _flatten(value: Any, *, prefix: str) -> list[tuple[str, Any]]:
    """Depth-first flatten to `(dotted.key, scalar)` pairs. Lists are indexed
    (`sources[0].total_amount`) so a claim can cite one counterparty rather than
    the whole list. Empty containers are dropped — there is nothing to cite."""
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            out.extend(_flatten(v, prefix=f"{prefix}.{k}"))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            out.extend(_flatten(v, prefix=f"{prefix}[{i}]"))
    else:
        out.append((prefix, value))
    return out


# ── The structured-output schema the model must answer in ─────────────────

#: The model returns its answer by calling THIS tool, and only this tool.
SUBMIT_TOOL_NAME = "submit_explanation"


def claims_schema() -> dict[str, Any]:
    """The JSON schema of a grounded answer. Every claim is *forced* to carry at
    least one citation by `minItems: 1` — the schema makes an uncited claim
    unrepresentable, so the validator's job is to check citations rather than to
    discover there aren't any."""
    return {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "minItems": 1,
                "description": (
                    "The explanation, one claim per sentence. Every number in a "
                    "statement MUST also appear in that claim's citations."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {
                            "type": "string",
                            "description": (
                                "One sentence of the explanation, in plain English, "
                                "for a compliance officer."
                            ),
                        },
                        "citations": {
                            "type": "array",
                            "minItems": 1,
                            "description": (
                                "Every fact this sentence relies on. Cite the exact "
                                "fact_key from the fact bundle and restate its value "
                                "verbatim. Do NOT compute new numbers: if a figure is "
                                "not in the bundle, do not state it."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "fact_key": {"type": "string"},
                                    "value": {
                                        "type": ["string", "number", "boolean", "null"]
                                    },
                                },
                                "required": ["fact_key", "value"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["statement", "citations"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["claims"],
        "additionalProperties": False,
    }


def submit_tool() -> dict[str, Any]:
    """The answer schema as a **forced tool call**, which is how the model must
    return a grounded answer.

    **Why a tool call and not `response_format: {"type": "json_schema"}`** — this
    is a live-verified provider defect, not a style preference. Measured against
    OpenRouter (`docs/METRICS.md` §13):

        openai/gpt-5-mini          response_format honoured
        google/gemini-2.5-flash    response_format honoured
        anthropic/claude-sonnet-4.5  response_format SILENTLY IGNORED -> prose

    Sonnet 4.5 advertises `structured_outputs` in OpenRouter's own
    `supported_parameters`, and then quietly returns prose anyway: no error, no
    refusal, just a string where the JSON should be. Had the substrate been built
    on `response_format`, the grounding contract would have degraded to nothing on
    the production model, and nothing would have raised.

    Tool-calling is honoured by every provider we tested, and it is the same
    mechanism the fact-gathering tools already rely on. So the answer comes back
    through a forced call to `submit_explanation`, whose arguments ARE the
    structured answer. One mechanism, portable, and it fails loudly rather than
    silently — which is the only property that matters for a control."""
    return {
        "type": "function",
        "function": {
            "name": SUBMIT_TOOL_NAME,
            "description": (
                "Submit the final grounded explanation. Every number in every "
                "statement must be cited from the fact bundle."
            ),
            "strict": True,
            "parameters": claims_schema(),
        },
    }


def submit_tool_choice() -> dict[str, Any]:
    """`tool_choice` forcing the model to answer via `submit_explanation` — it
    cannot reply with free prose that would bypass the validator entirely."""
    return {"type": "function", "function": {"name": SUBMIT_TOOL_NAME}}


def parse_response(payload: dict[str, Any]) -> list[Claim]:
    """Model JSON -> claims. Raises `GroundingError` on anything malformed: a
    response we cannot even parse must fail closed, never degrade to "no claims"
    (which `GroundingResult.ok` would happily call a clean pass)."""
    raw_claims = payload.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise GroundingError("response contained no claims")

    claims: list[Claim] = []
    for i, raw in enumerate(raw_claims):
        if not isinstance(raw, dict):
            raise GroundingError(f"claim {i} is not an object")
        statement = raw.get("statement")
        raw_citations = raw.get("citations")
        if not isinstance(statement, str) or not statement.strip():
            raise GroundingError(f"claim {i} has no statement")
        if not isinstance(raw_citations, list):
            raise GroundingError(f"claim {i} has no citations array")
        citations = tuple(
            Citation(fact_key=str(c.get("fact_key")), value=c.get("value"))
            for c in raw_citations
            if isinstance(c, dict)
        )
        claims.append(Claim(statement=statement, citations=citations))
    return claims


# ── The validator ─────────────────────────────────────────────────────────


def validate(claims: list[Claim], bundle: FactBundle) -> GroundingResult:
    """Run the three gates over every claim. Pure and deterministic: same claims
    plus same bundle always give the same verdict, which is what lets a regulator
    re-run it later against the persisted `ai_interactions.facts`."""
    result = GroundingResult()

    for claim in claims:
        reason = _reject_reason(claim, bundle)
        if reason is None:
            result.accepted.append(claim)
        else:
            result.rejected.append(Rejection(claim=claim, reason=reason))

    return result


def _reject_reason(claim: Claim, bundle: FactBundle) -> str | None:
    """None if the claim is grounded, else why it is not."""
    # Gate 0 — the schema forbids this, but the schema is the provider's promise.
    if not claim.citations:
        return "claim cites no facts"

    grounded_values: list[Any] = []

    for citation in claim.citations:
        # Gate 1 — the cited fact must exist.
        found, actual = bundle.resolve(citation.fact_key)
        if not found:
            return f"cites unknown fact_key {citation.fact_key!r}"

        # Gate 2 — and must hold the value the model says it holds.
        if not _values_match(citation.value, actual):
            return (
                f"misreports {citation.fact_key!r} as {citation.value!r} "
                f"(actual: {actual!r})"
            )
        grounded_values.append(actual)

    # Gate 3 — every number in the prose must be one of the numbers it cited.
    for number in _statement_numbers(claim.statement):
        if not any(_values_match(number, v) for v in grounded_values):
            return f"states ungrounded number {number!r} (not in any cited fact)"

    return None


def _values_match(claimed: Any, actual: Any) -> bool:
    """Is the model's restated value the same as the tool's?

    Numeric comparison is done numerically, not textually, so `71` matches `71.0`
    and `10000` matches `10,000` — those are the same number, and rejecting them
    would be pedantry that gets the validator disabled. Everything else compares
    as a trimmed, case-insensitive string, so `"HIGH"` matches `RiskLevel.HIGH`
    once stringified."""
    a, b = _as_number(claimed), _as_number(actual)
    if a is not None and b is not None:
        if math.isnan(a) or math.isnan(b):
            return False
        return math.isclose(a, b, rel_tol=_TOLERANCE, abs_tol=_TOLERANCE)

    if claimed is None or actual is None:
        return claimed is actual or str(claimed) == str(actual)

    return str(claimed).strip().casefold() == str(actual).strip().casefold()


def _as_number(value: Any) -> float | None:
    """Coerce to float, or None if it isn't a number. `bool` is excluded on
    purpose: Python says `True == 1`, but a model claiming `pep_status` is `1`
    when it is `True` is confused enough to be worth flagging."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("%", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _statement_numbers(statement: str) -> list[float]:
    """Numeric tokens a reader would take as *quantitative claims*.

    Two classes of number are removed before scanning, because neither is a
    quantity anyone could fabricate meaningfully:

    - **Timestamps and dates.** Found live: the model wrote "a single NEFT
      transaction of 250000.0 on 2026-03-01 12:00:00", and gate 3 rejected the
      whole (perfectly correct) claim because it read the `12` out of the clock
      time as an ungrounded figure. A false rejection is not a harmless
      over-caution — it is how a validator earns a reputation for crying wolf and
      gets switched off, taking the real control with it. A date says *when*, not
      *how much*.
    - **Currency prefixes** (`Rs.`, `₹`, `$`) are stripped so `Rs.10,000` reads
      as the number 10000 rather than being skipped for touching a letter. A
      figure hiding behind a currency symbol is exactly the one that must be
      grounded.

    Conservative by design (see `_NUMBER_IN_PROSE`): identifiers like `A1` and
    `DEMO-ACC-004` are not numeric claims either. The failure direction is
    deliberate — a missed number is a gap in gate 3, but a false positive
    discredits the whole gate."""
    cleaned = _TIMESTAMP.sub(" ", statement)
    cleaned = _CLOCK_TIME.sub(" ", cleaned)
    cleaned = _MONTH_YEAR.sub(" ", cleaned)
    cleaned = re.sub(r"(?i)(?:rs\.?|inr|usd|₹|\$)\s*", " ", cleaned)
    out: list[float] = []
    for token in _NUMBER_IN_PROSE.findall(cleaned):
        parsed = _as_number(token)
        if parsed is not None:
            out.append(parsed)
    return out
