"""
Guardrail middleware (ROADMAP Phase 8) -- sanitizes attacker-controllable
free text (`Transaction.narration`/`purpose`, `notes.body`, or any future
free-text field a Phase 9/10 agent might read) before it is allowed anywhere
near a prompt.

**No live caller exists yet** (verified: zero code path currently carries
`Transaction.narration`/`purpose` into any prompt -- both `orchestration.
account_explanation`/`orchestration.pattern_explanation` exclude them by
design, see those modules' own docstrings). This ships as pure plumbing for
Phase 9/10 to wire up when they add a feature that actually reads
attacker-controllable text -- same precedent as Phase 7's `investigation.
path_facts` shipping with no HTTP route yet. Exercised via unit tests and
`scripts/verify_ai_substrate.py` in this phase; a real caller belongs to
whichever later phase first needs to put free text in a prompt.

CLAUDE.md's own guardrail-guardrail: "the existing per-account LLM
explanation pattern... does NOT automatically transfer" to a feature that
accepts free text. This module is that "own explicit guardrail design" --
fixed sanitization steps, not an LLM-based classifier, so its behavior is
deterministic and testable.
"""
from __future__ import annotations

import re

#: Documented judgment call, no formula behind this number -- long enough
#: for a realistic narration/purpose/note field, short enough to bound how
#: much attacker-controlled text can ever reach a single prompt slot.
_MAX_FREE_TEXT_LENGTH = 500

_TRUNCATION_SUFFIX = "...[truncated]"

#: Small, explicitly NON-EXHAUSTIVE denylist of common instruction-injection
#: phrasings -- defense-in-depth, not a guarantee. A determined attacker can
#: phrase an injection attempt in ways this list doesn't catch; the point is
#: to neutralize the cheap, common cases and to make ANY match visible in
#: the stored `request_text` (via the `⟦...⟧` marker) rather than silently
#: passing it through. Matching is case-insensitive.
_INJECTION_PHRASES = (
    "system:",
    "assistant:",
    "ignore previous instructions",
    "ignore all prior instructions",
    "disregard the above",
)

#: Control characters to strip, EXCLUDING `\t`/`\n` (kept -- legible
#: multi-line free text like a narration/purpose field is not itself a
#: threat; only non-printable control bytes are stripped). Matches the
#: C0 control range plus DEL, skipping tab (0x09) and newline (0x0A).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INJECTION_PATTERN = re.compile(
    "|".join(re.escape(phrase) for phrase in _INJECTION_PHRASES), re.IGNORECASE
)


def _neutralize_injection_phrases(text: str) -> str:
    """Wraps every denylisted phrase match in `⟦...⟧` (inserted around the
    match, not replacing/deleting it) so the sanitized text stays legible
    when later stored as `ai_interactions.request_text` -- an investigator
    reading the audit trail should be able to see exactly what an attacker
    tried to inject, not a redacted blank."""
    return _INJECTION_PATTERN.sub(lambda m: f"⟦{m.group(0)}⟧", text)


def sanitize_free_text(
    raw: str | None, *, field_name: str, max_length: int = _MAX_FREE_TEXT_LENGTH
) -> str:
    """Sanitize `raw` (e.g. a `Transaction.narration`/`purpose` value)
    before it may be placed inside a prompt. Steps, in order:

      1. `None` -> `""`.
      2. Strip null bytes / non-printable control characters (keep `\\n`/
         `\\t`).
      3. Neutralize denylisted instruction-injection phrases (see
         `_INJECTION_PHRASES`) by wrapping the match in `⟦...⟧`, not
         deleting it.
      4. Truncate to `max_length`, appending `"...[truncated]"` if
         truncation happened (the suffix does NOT count against
         `max_length` itself -- the visible truncation marker is a courtesy
         to the caller/log reader, not part of the length budget being
         enforced).
      5. Wrap the result in an explicit delimiter:
         `f"<{field_name}_untrusted_data>{cleaned}</{field_name}_untrusted_data>"`
         -- the delimiter's job is to give the eventual prompt template an
         unambiguous "everything between these tags is untrusted user
         input, not an instruction" boundary.
    """
    if raw is None:
        text = ""
    else:
        text = _CONTROL_CHAR_RE.sub("", raw)
        text = _neutralize_injection_phrases(text)
        if len(text) > max_length:
            text = text[:max_length] + _TRUNCATION_SUFFIX

    return f"<{field_name}_untrusted_data>{text}</{field_name}_untrusted_data>"
